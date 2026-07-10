import type { Bundle } from "./types";

/** Çekirdek anahtarlar: ortak aksiyonlar, dil, giriş, kurum-dil alanı. */
export const core: Bundle = {
  tr: {
    "common.save": "Kaydet",
    "common.cancel": "İptal",
    "common.loading": "Yükleniyor…",
    "common.error": "Bir hata oluştu",
    "common.retry": "Tekrar dene",
    "common.language": "Dil",
    "common.forbidden.title": "Yetkiniz yok",
    "common.forbidden.desc":
      "Kurum yapılandırması yalnızca yöneticiler tarafından düzenlenebilir. Yetki için kurum yöneticinize başvurun.",
    "common.forbidden.desc.write":
      "Bu sayfa Analist ve Yönetici rollerine açıktır. Görüntüleyici rolü için kurum yöneticinize başvurun.",
    "common.forbidden.desc.admin":
      "Bu sayfa yalnızca Kurum Yöneticisi rolüne açıktır.",
    "common.forbidden.desc.super":
      "Bu sayfa yalnızca süper yönetici hesaplara açıktır.",

    "locale.tr": "Türkçe",
    "locale.en": "English",
    "locale.switchTitle": "Dili değiştir",

    "login.brand": "imga.ai",
    "login.title": "Hesabınıza giriş yapın",
    "login.email": "E-posta",
    "login.password": "Şifre",
    "login.submit": "Giriş yap",
    "login.submitting": "Giriş yapılıyor…",
    "login.failed.title": "Giriş başarısız",
    "login.failed.desc": "E-posta veya şifre hatalı.",
    "login.failed.generic": "Giriş yapılamadı, lütfen daha sonra tekrar deneyin.",
    "login.expired": "Oturumunuz sona erdi. Lütfen tekrar giriş yapın.",

    "tenant.language.label": "Kurum dili",
    "tenant.language.help":
      "Bu kurumun arayüzü ve yapay zeka çıktıları bu dilde olur. Sonradan Ayarlar'dan değiştirilebilir.",

    "common.batchPicker.prefix": "Yükleme",
    "common.batchPicker.all": "Tümü",
    "common.batchPicker.triggerAll": "Yükleme: Tümü",
    "common.batchPicker.selectedFallback": "Yükleme seçili",
    "common.batchPicker.none": "Henüz yükleme yok",
    "common.batchPicker.rows": "{n} satır",
    "common.batchPicker.today": "Bugün",
    "common.batchPicker.yesterday": "Dün",
    "common.batchStatus.completed": "Tamamlandı",
    "common.batchStatus.processing": "İşleniyor",
    "common.batchStatus.queued": "Kuyrukta",
    "common.batchStatus.failed": "Başarısız",
    "common.batchStatus.cancelled": "İptal edildi",
  },
  en: {
    "common.save": "Save",
    "common.cancel": "Cancel",
    "common.loading": "Loading…",
    "common.error": "Something went wrong",
    "common.retry": "Try again",
    "common.language": "Language",
    "common.forbidden.title": "You don't have permission",
    "common.forbidden.desc":
      "Organization configuration can only be edited by administrators. Contact your organization admin for access.",
    "common.forbidden.desc.write":
      "This page is available to the Analyst and Admin roles. Contact your organization admin for access.",
    "common.forbidden.desc.admin":
      "This page is available to the Organization Admin role only.",
    "common.forbidden.desc.super":
      "This page is available to super admin accounts only.",

    "locale.tr": "Türkçe",
    "locale.en": "English",
    "locale.switchTitle": "Change language",

    "login.brand": "imga.ai",
    "login.title": "Sign in to your account",
    "login.email": "Email",
    "login.password": "Password",
    "login.submit": "Sign in",
    "login.submitting": "Signing in…",
    "login.failed.title": "Sign-in failed",
    "login.failed.desc": "Incorrect email or password.",
    "login.failed.generic": "Sign-in failed, please try again later.",
    "login.expired": "Your session has expired. Please sign in again.",

    "tenant.language.label": "Organization language",
    "tenant.language.help":
      "This organization's interface and AI outputs will be in this language. It can be changed later in Settings.",

    "common.batchPicker.prefix": "Upload",
    "common.batchPicker.all": "All",
    "common.batchPicker.triggerAll": "Upload: All",
    "common.batchPicker.selectedFallback": "Upload selected",
    "common.batchPicker.none": "No uploads yet",
    "common.batchPicker.rows": "{n} rows",
    "common.batchPicker.today": "Today",
    "common.batchPicker.yesterday": "Yesterday",
    "common.batchStatus.completed": "Completed",
    "common.batchStatus.processing": "Processing",
    "common.batchStatus.queued": "Queued",
    "common.batchStatus.failed": "Failed",
    "common.batchStatus.cancelled": "Cancelled",
  },
};
