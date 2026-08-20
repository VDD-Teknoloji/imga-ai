"""Bir yüklemenin ``reviews.review_date``'ini dosyadaki gerçek tarihlerle
GERİYE DÖNÜK doldurur.

2026-08-20 — Kitap1.xlsx (21.684 satır) vakası: tarih kolonu yükleme
anında yakalanamadı (bkz. ``workers.file_parser`` docstring'i), tüm
satırlar ingest anına düştü ve dönem karşılaştırmaları (ör. /compare
Nisan-Mayıs) haftalarca boş kaldı. Aynı commit'te tespit güçlendirildi
ve açık kolon seçimi eklendi (migration 0044) — ama BU YÜKLEMEDEN ÖNCE
zaten analiz edilmiş satırlar için o düzeltmeler geriye işlemez. Bu
araç, orijinal dosyayı elden geçirip mevcut ``reviews`` satırlarını
GÜNCELLEYEREK o boşluğu kapatır.

Kullanım (api konteyneri içinde; dosyayı önce içeri kopyalayın, ör.
``docker cp Kitap1.xlsx imga-api:/tmp/``):

    python /tmp/backfill_review_dates.py <job_id> <dosya_yolu> \\
        [--date-column BASLIK] [--dry-run]

Argümanlar:
  job_id         analyze_batch_jobs.id (UUID) — hangi yüklemenin Review
                 satırları güncellenecek.
  dosya_yolu     Orijinal upload dosyası, konteyner içinde erişilebilir
                 bir yol. API'nin sakladığı upload_dir kopyası SİLİNMİŞ
                 olabilir (24h temizlik cron'u — bkz. AnalyzeBatchJob
                 model docstring'i), bu yüzden operatör dosyayı elle
                 sağlar.
  --date-column  Opsiyonel — dosyada hangi başlığın tarih olduğunu ELLE
                 belirtir (migration 0044'teki ``date_column`` ile aynı
                 anlam). Verilmezse ``file_parser``'ın güçlendirilmiş
                 otomatik tespiti çalışır (başlık deseni + değer-tabanlı
                 yedek — bkz. ``workers.file_parser._detect_date_column``).
  --dry-run      Hiçbir UPDATE çalıştırmaz; yalnızca eşleşme sayılarını
                 basar. İLK ÇALIŞTIRMADA HER ZAMAN önce bunu kullanın.

Akış:
  1. Dosyayı ``file_parser.iter_rows`` ile okur. BOŞ METİNLİ satırlar
     atlanır — worker da bunları ayrı, sabit bir hash'le (sha256(""))
     yazar (bkz. ``batch_analyzer._write_empty_reviews``); bu aracın
     konusu değiller ve dahil edilirlerse eşleme mantığını bozarlar.
  2. Job'ın Review satırlarını çeker — aynı gerekçeyle
     ``quality_flag='empty'`` satırlar HARİÇ tutulur.
  3. Güvenlik: dosyadaki ve DB'deki metin (text_hash) kümeleri büyük
     ölçüde örtüşmeli. Dosyanın kendi satır sayısına oranla %2'den
     fazlası (dosya ∪ DB, karşı tarafta HİÇ karşılığı olmayan satırlar)
     eşleşmiyorsa ABORT — muhtemelen yanlış dosya/job eşleştirildi.
     (``failed_rows`` nedeniyle küçük bir doğal fark beklenir — ``total
     rows`` işlenirken başarısız olan satırlar hiç Review üretmez; eşik
     bunu tolere edecek şekilde seçildi.)
  4. Eşleme (``match_dates_by_hash_order`` — SAF fonksiyon, I/O'suz,
     ayrı birim test edilebilir): her benzersiz text_hash için dosyadaki
     tarih listesi ile DB'deki o hash'li satırlar (``analyzed_at`` sırasıyla)
     POZİSYONEL olarak eşlenir.
       * Tekil hash (dosyada 1, DB'de 1 satır): eşleme BİREBİR KESİNDİR.
       * Tekrarlı hash (aynı metin N kez — şablon/otomasyon metinleri):
         AGREGA dağılım (kaç satır hangi TARİHE düştü) min(dosya, DB)
         kadarıyla birebir doğrudur; ama HANGİ DB satırının HANGİ tarihi
         aldığı, ``analyzed_at`` sırasının dosyanın kendi satır sırasıyla
         aynı olduğu varsayımına dayanan EN İYİ ÇABA'dır (paralel chunk
         işleme bu sırayı karıştırabilir). Satır-içi hassasiyet
         gerektiren bir analiz için bu araç YETERLİ DEĞİLDİR — yalnız
         agrega/dönemsel doğruluk hedefler.
  5. ``--dry-run`` ise burada durur (sayıları basar, hiçbir şey yazmaz).
     Değilse eşleşen satırlar TEK bir transaction'da güncellenir.
  6. Sonda: ``executive_snapshots`` temizliği (``reanalyzer.
     _bust_snapshot_cache`` ile aynı gerekçe — geçmiş herhangi bir
     ``review_date``'i değiştirebilir, günlük invalidate yetmez) +
     Redis analitik önek temizliği (``reanalyzer._bust_redis_caches``
     ile AYNI desen — bilinçli olarak KOPYALANDI, import EDİLMEDİ: bu
     script ``imga_api.workers.batch_analyzer`` / ``reanalyzer``'ın ağır
     BERT/LLM import zincirine bağımlı olmasın diye bağımsız kalır) +
     özet rapor.

``imga_db.create_engine("admin")`` + ``set_current_tenant`` deseni
kullanılır (bkz. ``workers.batch_analyzer._read_tenant_id`` /
``workers.reanalyzer._run_reanalysis``): tenant_id önce set_current_
tenant OLMADAN okunur (imga_admin RLS'i zaten bypass eder), sonraki her
işlem ayrı bir transaction'da set_current_tenant çağrısıyla açılır.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import UUID

from imga_api.workers.file_parser import (
    FileParseError,
    UnknownColumnError,
    iter_rows,
)
from imga_core.text_utils import review_text_hash
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import AnalyzeBatchJob, ExecutiveSnapshot, Review
from sqlalchemy import bindparam, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

#: Güvenlik eşiği — dosya/DB hash kümeleri bu orandan fazla ayrışıyorsa
#: (muhtemelen yanlış dosya/job eşleştirildi) script ABORT eder.
_MISMATCH_ABORT_THRESHOLD = 0.02

#: Redis'teki yorum-türevi analitik önbelleklerin anahtar önekleri.
#: ``reanalyzer._bust_redis_caches`` ile AYNI liste — KASITLI KOPYA (bkz.
#: modül docstring'i, adım 6): bu iki liste elle senkron tutulmalı,
#: biri değişirse diğeri de güncellenmeli.
_REDIS_CACHE_PREFIXES = ("briefing", "cohort", "heatmap", "wordcloud")


# ---------------------------------------------------------------------------
# Saf mantık — I/O yok, DB oturumu yok, ayrı birim test edilebilir.
# ---------------------------------------------------------------------------


def match_dates_by_hash_order(
    file_dates_by_hash: dict[str, list[datetime]],
    db_rows_by_hash: dict[str, list[tuple[UUID, datetime]]],
) -> dict[UUID, datetime]:
    """Her benzersiz ``text_hash`` için dosyadaki tarih listesini DB'deki
    o hash'e sahip satırlarla (``analyzed_at`` sırasına göre, eşitlikte
    ``id`` ile) POZİSYONEL olarak eşler.

    Yalnız İKİ TARAFTA DA bulunan hash'ler eşlenir — ``db_rows_by_hash``
    içinde karşılığı olmayan bir dosya hash'i sessizce atlanır (çağıran
    taraf bunu ayrı, güvenlik kontrolü amacıyla saymalı, bkz. script'in
    ana akışı / ``_safety_check``).

    Tekil hash (dosyada 1 tarih, DB'de 1 satır): eşleme BİREBİR
    KESİNDİR. Tekrarlı hash'lerde (aynı metin dosyada N kez geçiyorsa —
    şablon/otomasyon metinleri tipik örnek) çıkış AGREGA olarak
    doğrudur: dosyadaki tarihlerin min(N, DB satır sayısı) kadarı
    KULLANILIR, hiçbiri kaybolmaz/tekrarlanmaz. Ama HANGİ DB satırının
    HANGİ tarihi aldığı, ``analyzed_at`` sırasının dosyanın kendi satır
    sırasıyla aynı olduğu varsayımına dayanan EN İYİ ÇABA'dır — worker
    satırları dosya sırasına yakın yazar ama paralel chunk işleme
    (``chunk_concurrency > 1``) bu sırayı karıştırabilir. Satır-içi
    (row-level) hassasiyet gerektiren bir analiz için bu YETERLİ
    DEĞİLDİR; yalnız agrega/dönemsel (aylık/haftalık trend) doğruluk
    hedefler — ki asıl kayıp da zaten oydu.

    Taraflardan biri diğerinden UZUNSA (ör. dosyada bu hash için 5
    tarih var ama DB'de yalnız 3 satır — bazı satırlar ``failed_rows``'a
    düştüğü için; ya da tersi) eşleme ``min(len, len)`` kadar sürer;
    fazlalık taraf sessizce atlanır — güncellenmeyen DB satırları
    mevcut ``review_date``'ini korur, kullanılmayan dosya tarihleri
    hiçbir yere yazılmaz.
    """
    assignments: dict[UUID, datetime] = {}
    for text_hash, dates in file_dates_by_hash.items():
        db_rows = db_rows_by_hash.get(text_hash)
        if not db_rows:
            continue
        ordered_db_rows = sorted(db_rows, key=lambda r: (r[1], str(r[0])))
        for (review_id, _analyzed_at), review_date in zip(
            ordered_db_rows, dates, strict=False
        ):
            assignments[review_id] = review_date
    return assignments


def safety_check(
    file_row_counts_by_hash: dict[str, int],
    db_rows_by_hash: dict[str, list[tuple[UUID, datetime]]],
) -> tuple[int, int, float]:
    """Dosya ve DB'deki metin (text_hash) kümelerinin ne kadar örtüştüğünü
    ölçer. Saf fonksiyon.

    ``file_row_counts_by_hash`` BİLEREK tarih-çözümünden bağımsızdır
    (yalnız "bu metin dosyada var mı" sorusuna bakar) — eşleme girdisi
    olan ``match_dates_by_hash_order``'ın tarih-filtreli listesini
    kullanmak, tarihleri seyrek dolu ama İÇERİĞİ doğru bir dosyada
    yanlışlıkla ABORT'a yol açardı.

    Returns:
        ``(unmatched_file_rows, unmatched_db_rows, ratio)`` — ratio,
        ``(unmatched_file_rows + unmatched_db_rows) / toplam dosya
        satırı``'dır (dosya satırı 0'sa 0.0).
    """
    file_hashes = set(file_row_counts_by_hash)
    db_hashes = set(db_rows_by_hash)
    total_file_rows = sum(file_row_counts_by_hash.values())
    unmatched_file_rows = sum(
        file_row_counts_by_hash[h] for h in file_hashes - db_hashes
    )
    unmatched_db_rows = sum(
        len(db_rows_by_hash[h]) for h in db_hashes - file_hashes
    )
    ratio = (
        (unmatched_file_rows + unmatched_db_rows) / total_file_rows
        if total_file_rows > 0
        else 0.0
    )
    return unmatched_file_rows, unmatched_db_rows, ratio


# ---------------------------------------------------------------------------
# Dosya + DB okuma
# ---------------------------------------------------------------------------


def extract_file_dates_by_hash(
    file_path: Path,
    *,
    text_column: str,
    date_column: str | None,
) -> tuple[dict[str, list[datetime]], dict[str, int]]:
    """Dosyayı ``iter_rows`` ile tarar ve iki gruplama döner:

      * ``dates_by_hash`` — yalnız ``review_date`` ÇÖZÜLEN satırlar,
        dosya sırası korunarak. Eşleme (``match_dates_by_hash_order``)
        girdisi budur; ``None`` bir DB satırına atanamaz (``review_date``
        NOT NULL), bu yüzden çözülmeyenler listeye hiç girmez.
      * ``row_counts_by_hash`` — BOŞ OLMAYAN (metin taşıyan) TÜM
        satırlar, tarih çözülsün çözülmesin. Güvenlik kontrolü
        (``safety_check``) budur — "bu metin dosyada var mı" sorusu
        tarih kalitesinden bağımsız olmalı.

    Boş metinli satırlar (``not parsed.text``) her iki gruplamadan da
    tamamen dışlanır — modül docstring'i madde 1.
    """
    dates_by_hash: dict[str, list[datetime]] = defaultdict(list)
    row_counts_by_hash: dict[str, int] = defaultdict(int)
    for parsed in iter_rows(
        file_path, text_column=text_column, date_column=date_column
    ):
        if not parsed.text:
            continue
        text_hash = review_text_hash(parsed.text)
        row_counts_by_hash[text_hash] += 1
        if parsed.review_date is not None:
            dates_by_hash[text_hash].append(parsed.review_date)
    return dict(dates_by_hash), dict(row_counts_by_hash)


async def fetch_db_rows_by_hash(
    session: AsyncSession, job_id: UUID
) -> dict[str, list[tuple[UUID, datetime]]]:
    """Job'ın (boş-metin HARİÇ) Review satırlarını ``text_hash``'e göre
    gruplar. Sıralama burada yapılmaz — ``match_dates_by_hash_order``
    kendi ``(analyzed_at, id)`` sıralamasını uygular, bu fonksiyon yalnız
    gruplar."""
    stmt = (
        select(Review.id, Review.text_hash, Review.analyzed_at)
        .where(Review.batch_job_id == job_id)
        .where(Review.deleted_at.is_(None))
        # quality_flag='empty' satırların HEPSİ aynı (boş metin) hash'i
        # paylaşır — dahil edilirse eşleme mantığı bozulur. Diğer tüm
        # bayraklar (duplicate/informational/meaningless/None) kendi
        # GERÇEK metinlerinin hash'ini taşır, dahil edilmeleri doğrudur.
        .where(or_(Review.quality_flag.is_(None), Review.quality_flag != "empty"))
    )
    rows = (await session.execute(stmt)).all()
    out: dict[str, list[tuple[UUID, datetime]]] = defaultdict(list)
    for review_id, text_hash, analyzed_at in rows:
        out[text_hash].append((review_id, analyzed_at))
    return dict(out)


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------


async def _apply_updates(
    session: AsyncSession, assignments: dict[UUID, datetime]
) -> None:
    """Toplu UPDATE — tek ``execute`` çağrısıyla executemany (SQLAlchemy
    2.0 "multiple parameter sets" deseni). 21K satırlık bir job'da
    tek-tek round-trip yerine tek istekte akar."""
    stmt = (
        update(Review)
        .where(Review.id == bindparam("_review_id"))
        .values(review_date=bindparam("_review_date"))
    )
    params = [
        {"_review_id": review_id, "_review_date": review_date}
        for review_id, review_date in assignments.items()
    ]
    await session.execute(stmt, params)


async def _bust_redis_caches(tenant_id: UUID) -> None:
    """``reanalyzer._bust_redis_caches`` ile AYNI mantık — KASITLI KOPYA,
    import değil (modül docstring'i, adım 6). Best-effort: Redis
    erişilemezse UPDATE'ler yine de kalıcıdır, en fazla TTL dolana kadar
    bayat önbellek görünür."""
    try:
        from imga_api.cache.redis_client import get_redis_client

        client = get_redis_client()
        keys = [
            key
            for prefix in _REDIS_CACHE_PREFIXES
            async for key in client.scan_iter(f"{prefix}:{tenant_id}:*")
        ]
        if keys:
            await client.delete(*keys)
        print(f"[backfill] redis önbellek temizliği: {len(keys)} anahtar silindi.")
    except Exception as exc:
        print(
            f"[backfill] UYARI: redis önbellek temizliği başarısız (kritik "
            f"değil, UPDATE'ler kalıcı): {exc}"
        )


async def run(
    job_id: UUID,
    file_path: Path,
    *,
    date_column: str | None,
    dry_run: bool,
) -> int:
    admin_engine = create_engine("admin")
    admin_factory = create_session_factory(admin_engine)
    try:
        # tenant_id set_current_tenant OLMADAN okunur — imga_admin RLS'i
        # zaten bypass eder (bkz. batch_analyzer._read_tenant_id ile aynı
        # desen). Sonraki her transaction set_current_tenant ile açılır.
        async with admin_factory() as session, session.begin():
            job_row = (
                await session.execute(
                    select(
                        AnalyzeBatchJob.tenant_id,
                        AnalyzeBatchJob.text_column,
                        AnalyzeBatchJob.file_name,
                    ).where(AnalyzeBatchJob.id == job_id)
                )
            ).first()
        if job_row is None:
            print(f"HATA: job {job_id} bulunamadı.", file=sys.stderr)
            return 1
        tenant_id, job_text_column, file_name = job_row

        print(f"[backfill] job={job_id} dosya='{file_name}' tenant={tenant_id}")
        print(f"[backfill] okunan dosya: {file_path}")
        print(
            "[backfill] tarih kolonu: "
            + (f"ELLE seçildi: '{date_column}'" if date_column else "OTOMATİK TESPİT")
        )

        try:
            file_dates_by_hash, file_row_counts_by_hash = extract_file_dates_by_hash(
                file_path, text_column=job_text_column, date_column=date_column
            )
        except (FileParseError, UnknownColumnError) as exc:
            print(f"HATA: dosya okunamadı: {exc}", file=sys.stderr)
            return 1

        async with admin_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            db_rows_by_hash = await fetch_db_rows_by_hash(session, job_id)

        total_file_rows = sum(file_row_counts_by_hash.values())
        total_dated_file_rows = sum(len(v) for v in file_dates_by_hash.values())
        total_db_rows = sum(len(v) for v in db_rows_by_hash.values())
        unmatched_file, unmatched_db, ratio = safety_check(
            file_row_counts_by_hash, db_rows_by_hash
        )

        print(
            f"[backfill] dosya: {len(file_row_counts_by_hash)} benzersiz metin, "
            f"{total_file_rows} boş-olmayan satır ({total_dated_file_rows} tarihli)"
        )
        print(
            f"[backfill] DB: {len(db_rows_by_hash)} benzersiz metin, "
            f"{total_db_rows} satır (quality_flag='empty' hariç)"
        )
        print(
            f"[backfill] eşleşmeyen: yalnız-dosya {unmatched_file}, "
            f"yalnız-DB {unmatched_db} satır (oran %{ratio * 100:.2f})"
        )

        if ratio > _MISMATCH_ABORT_THRESHOLD:
            print(
                f"ABORT: eşleşmeyen satır oranı %{ratio * 100:.2f}, eşik "
                f"%{_MISMATCH_ABORT_THRESHOLD * 100:.0f}'i aşıyor. Muhtemelen "
                "yanlış dosya bu job'a eşleştirildi — devam edilmiyor.",
                file=sys.stderr,
            )
            return 1

        assignments = match_dates_by_hash_order(file_dates_by_hash, db_rows_by_hash)
        print(f"[backfill] eşlenen (güncellenecek) satır: {len(assignments)}")

        if dry_run:
            print("[backfill] --dry-run: hiçbir UPDATE çalıştırılmadı.")
            return 0

        if not assignments:
            print("[backfill] güncellenecek satır yok, çıkılıyor.")
            return 0

        async with admin_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            await _apply_updates(session, assignments)

        # Yeniden analiz işçisiyle aynı gerekçe (reanalyzer.
        # _bust_snapshot_cache): geçmiş herhangi bir review_date
        # değişebilir, günlük invalidate yetmez — kurumun tüm anlık
        # görüntüleri düşer, bir sonraki okuma taze hesaplar.
        async with admin_factory() as session, session.begin():
            await set_current_tenant(session, tenant_id)
            await session.execute(
                delete(ExecutiveSnapshot).where(
                    ExecutiveSnapshot.tenant_id == tenant_id
                )
            )
        await _bust_redis_caches(tenant_id)

        print(f"[backfill] TAMAMLANDI: {len(assignments)} satır güncellendi.")
        return 0
    finally:
        await admin_engine.dispose()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("job_id", type=UUID, help="analyze_batch_jobs.id")
    parser.add_argument(
        "file_path", type=Path, help="Orijinal upload dosyasının yolu"
    )
    parser.add_argument(
        "--date-column",
        dest="date_column",
        default=None,
        help=(
            "Dosyadaki tarih kolonu başlığı. Verilmezse file_parser'ın "
            "güçlendirilmiş otomatik tespiti çalışır."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="UPDATE çalıştırmaz; yalnızca eşleşme sayılarını basar.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    if not args.file_path.exists():
        print(f"HATA: dosya bulunamadı: {args.file_path}", file=sys.stderr)
        sys.exit(1)
    exit_code = asyncio.run(
        run(
            args.job_id,
            args.file_path,
            date_column=args.date_column,
            dry_run=args.dry_run,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
