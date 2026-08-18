import type { Bundle } from "./types";

/** admin alan sözlüğü (Sprint 12 i18n). */
export const admin: Bundle = {
  tr: {
    // --- ortak (admin geneli) ---------------------------------------------
    "admin.common.listError": "Liste alınamadı.",
    "admin.common.noRecords": "Kayıt yok.",
    "admin.common.recordCount": "{n} kayıt",
    "admin.action.cancel": "Vazgeç",
    "admin.action.ok": "Tamam",
    "admin.field.name": "İsim",
    "admin.field.slug": "Slug",
    "admin.field.plan": "Plan",
    "admin.field.automation": "Otomasyon",
    "admin.field.email": "E-posta",
    "admin.error.superAdminRequired": "Bu işlem için süper-yönetici yetkisi gerekli.",
    "admin.error.invalidForm": "Form alanları geçersiz.",
    "admin.error.unexpected": "Beklenmeyen bir hata oluştu.",
    "admin.error.notFound": "Kurum bulunamadı.",

    // --- davet linki bloğu (create + invite paylaşır) ---------------------
    "admin.invite.linkLabel": "Davet linki",
    "admin.invite.copy": "Kopyala",
    "admin.invite.copied": "Link kopyalandı",
    "admin.invite.copyFailed": "Kopyalanamadı; manuel seç ve kopyala.",
    "admin.invite.linkHelp": "Bu linki davet edilenle paylaşın. 7 gün geçerli.",
    "admin.invite.onlyOnce": "tek sefer",

    // --- Kurumlar ---------------------------------------------------------
    "admin.tenants.forbidden.title": "Yetkiniz yok",
    "admin.tenants.forbidden.desc":
      "Kurum yönetimi sayfası yalnızca süper-yönetici hesaplara açıktır.",
    "admin.tenants.title": "Kurumlar",
    "admin.tenants.subtitle":
      "Süper-yönetici görünümü. Kurum oluştur, düzenle, davet gönder veya soft-delete.",
    "admin.tenants.new": "Yeni Kurum",
    "admin.tenants.loadError": "Kurum listesi yüklenemedi.",
    "admin.tenants.col.created": "Oluşturuldu",
    "admin.tenants.col.actions": "Aksiyonlar",
    "admin.tenants.action.edit": "Düzenle",
    "admin.tenants.action.invite": "Davet",
    "admin.tenants.action.llm": "LLM Ayarları",
    "admin.tenants.action.engagement": "Katılım Eşikleri",
    "admin.tenants.action.delete": "Sil",
    "admin.tenants.empty.title": "Henüz kurum yok",
    "admin.tenants.empty.desc": "İlk kurumu oluştur ve admin davetini gönder.",

    // --- katılım eşikleri (yalnız süper yönetici) -------------------------
    "admin.engagement.title": "Katılım Eşikleri",
    "admin.engagement.desc":
      "{tenant} — katılım oranının hangi aralıkta ne anlama geldiğini belirleyin.",
    "admin.engagement.usingDefaults":
      "Bu kurum için henüz özel eşik tanımlanmadı; varsayılanlar gösteriliyor.",
    "admin.engagement.field.minPct": "Alt sınır (%)",
    "admin.engagement.field.label": "Etiket",
    "admin.engagement.addBand": "Bant ekle",
    "admin.engagement.removeBand": "Bandı kaldır",
    "admin.engagement.help":
      "Her bant kendi alt sınırından bir sonrakinin alt sınırına kadar geçerlidir. İlk bant %0'dan başlar; sınırdaki oran üst banda düşer.",
    "admin.engagement.save": "Kaydet",
    "admin.engagement.saving": "Kaydediliyor…",
    "admin.engagement.toast.saved": "Katılım eşikleri güncellendi.",
    "admin.engagement.toast.saveError": "Eşikler kaydedilemedi.",
    "admin.engagement.error.minPctRange":
      "Alt sınır 0 ile 100 arasında bir sayı olmalı.",
    "admin.engagement.error.labelRequired": "Etiket boş olamaz.",
    "admin.engagement.error.atLeastOne": "En az bir bant tanımlayın.",
    "admin.engagement.error.startsAtZero": "İlk bandın alt sınırı %0 olmalı.",
    "admin.engagement.error.ascending":
      "Alt sınırlar artan sırada ve birbirinden farklı olmalı.",

    // --- llm (kurum başına model + API anahtarı yönetimi) -----------------
    // 2026-08-09: yönetim kurumdan alınıp süper yöneticiye verildi;
    // kurum tarafında yalnız salt-okur görünüm kaldı.
    "admin.llm.title": "Yapay Zekâ Ayarları",
    "admin.llm.subtitle":
      "Kurumun yapay zekâ sağlayıcısı, modeli ve API anahtarları. En üstteki aktif kayıt kazanır; alttakiler sırayla yedektir.",
    "admin.llm.subtitleFor":
      "{tenant} — yapay zekâ sağlayıcısı, modeli ve API anahtarları. En üstteki aktif kayıt kazanır; alttakiler sırayla yedektir.",
    "admin.llm.backToTenants": "Kurumlar",
    "admin.llm.loadError": "Anahtarlar yüklenemedi.",
    "admin.llm.empty":
      "Bu kurum için henüz anahtar eklenmemiş. Aşağıdaki formdan ilk anahtarı ekleyin.",
    "admin.llm.primary": "Birincil",
    "admin.llm.backup": "Yedek {n}",
    "admin.llm.lastFailed": "Son başarısız: {date}",
    "admin.llm.warning": "dikkat",
    "admin.llm.toggleActive": "Etkinleştir/Devre dışı",
    "admin.llm.editLabel": "Etiketi düzenle",
    "admin.llm.dragHandle": "Sıralama tutamağı",
    "admin.llm.reorderFailed": "Sıralama kaydedilemedi.",
    "admin.llm.labelUpdateFailed": "Etiket güncellenemedi.",
    "admin.llm.statusUpdateFailed": "Durum güncellenemedi.",
    "admin.llm.keyDeleted": "Anahtar silindi.",
    "admin.llm.deleteFailed": "Silme başarısız.",
    "admin.llm.delete": "Sil",
    "admin.llm.add": "Ekle",
    "admin.llm.deleteAria": "{label} sil",
    "admin.llm.deleteConfirmTitle": "API anahtarı silinsin mi?",
    "admin.llm.deleteConfirmDesc":
      "anahtarı kalıcı olarak silinecek. Bu işlem geri alınamaz; anahtar sağlayıcı tarafında geçerli kalmaya devam eder, isterseniz tekrar ekleyebilirsiniz.",
    "admin.llm.addTitle": "Yeni anahtar ekle",
    "admin.llm.labelField": "Etiket",
    "admin.llm.labelPlaceholder": "Örn. Birincil Hesap",
    "admin.llm.apiKeyField": "API anahtarı",
    "admin.llm.hideKey": "Anahtarı gizle",
    "admin.llm.showKey": "Anahtarı göster",
    "admin.llm.keyPrefixWarning": "Gemini anahtarları \"AIza\" ile başlar.",
    "admin.llm.orKeyPrefixWarning":
      "OpenRouter anahtarları \"sk-or-\" ile başlar.",
    "admin.llm.keyAdded": "Anahtar eklendi.",
    "admin.llm.addFailed": "Anahtar eklenemedi.",
    "admin.llm.providerField": "Sağlayıcı",
    "admin.llm.modelField": "Model",
    "admin.llm.modelDefault": "Varsayılan model",
    "admin.llm.modelSearchPlaceholder": "Model ara…",
    "admin.llm.modelRecommended": "Önerilenler",
    "admin.llm.modelAll": "Tüm modeller",
    "admin.llm.modelEmpty": "Eşleşen model yok.",
    "admin.llm.modelChanged": "Model güncellendi.",
    "admin.llm.modelChangeFailed": "Model güncellenemedi.",

    // --- LLM Denetimi -----------------------------------------------------
    "admin.llmAudit.callType.all": "Tümü",
    "admin.llmAudit.callType.classification": "Sınıflandırma",
    "admin.llmAudit.callType.briefing": "Brifing",
    "admin.llmAudit.callType.strategicReport": "Stratejik rapor",
    "admin.llmAudit.callType.actionExtraction": "Eylem çıkarımı",
    "admin.llmAudit.callType.okr": "OKR",
    "admin.llmAudit.title": "LLM Çağrı Denetimi",
    "admin.llmAudit.subtitle":
      "Her LLM çağrısı için prompt hash + model meta + token + hata kaydı. AI kararlarımızın izlenebilirliği.",
    "admin.llmAudit.summary.totalCalls": "Son 30 gün — toplam çağrı",
    "admin.llmAudit.summary.failures": "Hata sayısı",
    "admin.llmAudit.summary.totalTokens": "Toplam token",
    "admin.llmAudit.dailyChart": "Günlük token + çağrı",
    "admin.llmAudit.result.all": "Tüm sonuçlar",
    "admin.llmAudit.result.ok": "Yalnızca başarılı",
    "admin.llmAudit.result.fail": "Yalnızca hata",
    "admin.llmAudit.detail.prompt": "Prompt",
    "admin.llmAudit.detail.promptHash": "Prompt hash",
    "admin.llmAudit.detail.provider": "Provider",
    "admin.llmAudit.detail.tokensInOut": "Token (giriş/çıkış)",
    "admin.llmAudit.detail.requestId": "Request id",
    "admin.llmAudit.detail.error": "Hata",

    // --- Karar Geçmişi ----------------------------------------------------
    "admin.decisionAudit.title": "Karar Geçmişi",
    "admin.decisionAudit.subtitle":
      "Yöneticilerin onay / red / atama / hedef gibi kararları zaman damgalı kayıt.",
    "admin.decisionAudit.allTypes": "Tüm karar tipleri",
    "admin.decisionAudit.rationale": "Gerekçe:",
    "admin.decisionAudit.type.briefingAcknowledged": "Yönetici özeti onaylandı",
    "admin.decisionAudit.type.briefingDismissed": "Yönetici özeti reddedildi",
    "admin.decisionAudit.type.strategicReportApproved": "Stratejik rapor onaylandı",
    "admin.decisionAudit.type.strategicReportRejected": "Stratejik rapor reddedildi",
    "admin.decisionAudit.type.actionItemAssigned": "Aksiyon atandı",
    "admin.decisionAudit.type.actionItemPriorityChanged": "Aksiyon önceliği değişti",
    "admin.decisionAudit.type.slaRuleChanged": "SLA kuralı değişti",
    "admin.decisionAudit.type.kpiGoalSet": "KPI hedefi konuldu",
    "admin.decisionAudit.type.webhookDispatchedManually": "Bildirim manuel gönderildi",
    "admin.decisionAudit.type.tenantSettingChanged": "Kurum ayarı değişti",
    "admin.decisionAudit.type.promptTemplateOverridden": "İstem şablonu özelleştirildi",

    // --- Prompt Şablonları ------------------------------------------------
    "admin.promptTemplates.title": "Prompt Şablonları",
    "admin.promptTemplates.subtitle":
      "LLM çağrıları için sistem + kullanıcı istemleri. Varsayılanları kopyalayıp kuruma özel şablon oluşturun. Test butonu sunucuda Jinja2 çalıştırır.",
    "admin.promptTemplates.defaultsError":
      "Varsayılan şablonlar alınamadı; yalnızca kayıtlı özelleştirmeler listeleniyor.",
    "admin.promptTemplates.badge.custom": "özel",
    "admin.promptTemplates.badge.default": "varsayılan",
    "admin.promptTemplates.selectPrompt": "Soldan bir şablon seçin.",
    "admin.promptTemplates.override": "Kuruma özel",
    "admin.promptTemplates.defaultLabel": "Varsayılan",
    "admin.promptTemplates.systemPrompt": "Sistem istemi",
    "admin.promptTemplates.userPromptLabel":
      "Kullanıcı istem şablonu (Jinja2 — {{ variable }} kullanın)",
    "admin.promptTemplates.userPromptLockedHint":
      "Bu şablonda yorum listesi sistem tarafından kurulur — yalnız sistem talimatı düzenlenebilir.",
    "admin.promptTemplates.expectedVars": "Beklenen değişkenler:",
    "admin.promptTemplates.updateOverride": "Özelleştirmeyi güncelle",
    "admin.promptTemplates.createOverride": "Kuruma özel oluştur",
    "admin.promptTemplates.deleteConfirm": "Özelleştirme silinsin? Kurum varsayılana döner.",
    "admin.promptTemplates.deleteOverride": "Özelleştirmeyi sil",
    "admin.promptTemplates.testRun": "Test çalıştırması",
    "admin.promptTemplates.variablesJson": "Değişkenler (JSON)",
    "admin.promptTemplates.varsPlaceholder": '{"text": "örnek", "categories": ["a", "b"]}',
    "admin.promptTemplates.testButton": "Test et",
    "admin.promptTemplates.running": "Çalıştırılıyor…",
    "admin.promptTemplates.virtualTestHint":
      "Test çalıştırması kayıtlı şablonlarda çalışır — önce özelleştirme oluşturun.",
    "admin.promptTemplates.name.swot": "SWOT Analizi",
    "admin.promptTemplates.name.okr": "OKR Hedefleri",
    "admin.promptTemplates.name.briefing": "Yönetici Özeti",
    "admin.promptTemplates.name.unifiedClassifier": "Yorum Sınıflandırma",
    "admin.promptTemplates.toast.updated": "Özelleştirme güncellendi.",
    "admin.promptTemplates.toast.created": "Kuruma özel şablon oluşturuldu.",
    "admin.promptTemplates.toast.varsParseError": "Variables JSON parse edilemedi.",
    "admin.promptTemplates.toast.testOk": "Test başarılı ({source}).",
    "admin.promptTemplates.toast.deleted": "Özelleştirme silindi.",

    // --- Kurum oluştur diyaloğu -------------------------------------------
    "admin.tenantCreate.title": "Yeni kurum",
    "admin.tenantCreate.desc":
      "İsim ve slug zorunlu. Opsiyonel olarak ilk admin daveti aynı işlemde oluşturulabilir.",
    "admin.tenantCreate.slugHelp":
      "URL'de görünür. Sadece lowercase harf, rakam ve tire. Sonradan değiştirilemez.",
    "admin.tenantCreate.seedAdminLabel": "İlk admin daveti gönder",
    "admin.tenantCreate.seedAdminHelp": "Kurum oluşturulurken davet token'ı üretilir.",
    "admin.tenantCreate.fullName": "Tam ad",
    "admin.tenantCreate.create": "Oluştur",
    "admin.tenantCreate.creating": "Oluşturuluyor...",
    "admin.tenantCreate.toast.createdTitle": "Kurum oluşturuldu",
    "admin.tenantCreate.toast.createdInvite": "İlk admin daveti hazır — linki paylaşın.",
    "admin.tenantCreate.toast.createError": "Kurum oluşturulamadı",
    "admin.tenantCreate.error.slugTaken": "Bu slug zaten kullanılıyor.",
    "admin.tenantCreate.success.title": "{name} oluşturuldu",
    "admin.tenantCreate.success.desc1": "İlk admin için davet linki hazır. Bu link sadece ",
    "admin.tenantCreate.success.desc2": " gösterilir — modalı kapatmadan paylaş.",
    "admin.tenantCreate.success.done": "Tamam, paylaştım",
    "admin.tenantCreate.success.aiSuggestNote":
      "Kurulumdan sonra Ayarlar → Taksonomiler'den yapay zekâya kategori önerttirin.",
    "admin.tenantCreate.step.next": "İleri",
    "admin.tenantCreate.step.back": "Geri",
    "admin.tenantCreate.step.skip": "Atla",
    "admin.tenantCreate.step.basicsShort": "Temel",
    "admin.tenantCreate.step.profileShort": "Profil",
    "admin.tenantCreate.step.inviteShort": "Davet",
    "admin.tenantCreate.step.profileDesc":
      "Opsiyonel — sektör/büyüklük/iş tanımı SWOT, OKR ve brifing üretimini isabetlendirir. Tamamen atlanabilir.",
    "admin.tenantCreate.step.profileHelp":
      "Bu adım opsiyoneldir; boş bırakıp \"Atla\" ile devam edebilirsiniz.",

    // --- Kurum düzenle diyaloğu -------------------------------------------
    "admin.tenantEdit.title": "Kurum düzenle",
    "admin.tenantEdit.desc":
      "Slug değiştirilemez. İsim ve plan / otomasyon ayarlarını güncelleyebilirsin.",
    "admin.tenantEdit.slugLabel": "Slug (değişmez)",
    "admin.tenantEdit.save": "Kaydet",
    "admin.tenantEdit.saving": "Kaydediliyor...",
    "admin.tenantEdit.toast.updated": "Kurum güncellendi",
    "admin.tenantEdit.toast.updateError": "Güncellenemedi",

    // --- Kurum sil diyaloğu -----------------------------------------------
    "admin.tenantDelete.title": "{name} adlı kurumu sil",
    "admin.tenantDelete.desc":
      "Bu kurumu silmek üzeresin. Tüm verisi soft-delete edilir; gerekirse veritabanı seviyesinde geri yüklenebilir. Aktif kullanıcılar artık bu kurumu göremez.",
    "admin.tenantDelete.delete": "Sil",
    "admin.tenantDelete.deleting": "Siliniyor...",
    "admin.tenantDelete.toast.deletedTitle": "Kurum silindi",
    "admin.tenantDelete.toast.deletedDesc": "{name} arşivlendi (soft-delete).",
    "admin.tenantDelete.toast.deleteError": "Silinemedi",
    "admin.tenantDelete.error.notFound": "Kurum zaten silinmiş veya bulunamadı.",

    // --- Kurum davet diyaloğu ---------------------------------------------
    "admin.tenantInvite.ready": "Davet hazır",
    "admin.tenantInvite.ready.desc1": "Bu link sadece ",
    "admin.tenantInvite.ready.desc2":
      " gösterilir — modalı kapatmadan davet edilenle paylaş. 7 gün geçerli.",
    "admin.tenantInvite.title": "{name} için davet",
    "admin.tenantInvite.desc":
      "Davet edilecek e-posta ve rolü seç. Token tek seferlik gösterilir, doğrudan kullanıcıyla paylaşmak için.",
    "admin.tenantInvite.emailPlaceholder": "kullanici@firma.com",
    "admin.tenantInvite.role": "Rol",
    "admin.tenantInvite.create": "Davet oluştur",
    "admin.tenantInvite.preparing": "Hazırlanıyor...",
    "admin.tenantInvite.toast.readyDesc": "{name} için.",
    "admin.tenantInvite.toast.error": "Davet oluşturulamadı",
    "admin.tenantInvite.error.forbidden": "Yetkin yok.",
    "admin.tenantInvite.error.duplicate": "Bu e-posta için zaten açık davet var.",
    "admin.tenantInvite.error.invalidEmail": "E-posta geçersiz.",

    // --- Bekleyen Bildirimler ---------------------------------------------
    "admin.pendingNotifications.title": "Bekleyen Bildirimler",
    "admin.pendingNotifications.subtitle":
      "Manuel modda tetiklenen SLA bildirimleri. Buradan onay vererek Slack/Teams kanallarına gönder veya iptal et.",
    "admin.pendingNotifications.slaRules": "SLA kuralları",
    "admin.pendingNotifications.total": "Toplam {n}",
    "admin.pendingNotifications.tab.pending": "Bekleyen",
    "admin.pendingNotifications.tab.sent": "Gönderildi",
    "admin.pendingNotifications.tab.failed": "Başarısız",
    "admin.pendingNotifications.tab.dismissed": "İptal",
    "admin.pendingNotifications.tab.all": "Hepsi",
    "admin.pendingNotifications.noRuleName": "(kural adı yok)",
    "admin.pendingNotifications.retries": "{n} deneme",
    "admin.pendingNotifications.dispatch": "Gönder",
    "admin.pendingNotifications.cancel": "İptal",
    "admin.pendingNotifications.status.pending": "Bekliyor",
    "admin.pendingNotifications.status.sent": "Gönderildi",
    "admin.pendingNotifications.status.failed": "Başarısız",
    "admin.pendingNotifications.status.dismissed": "İptal",
    "admin.pendingNotifications.empty.pending":
      "Bekleyen webhook yok. SLA breach olduğunda burada görünecek.",
    "admin.pendingNotifications.empty.filtered": "Bu filtrede kayıt bulunamadı.",
    "admin.pendingNotifications.prev": "Önceki",
    "admin.pendingNotifications.next": "Sonraki",
    "admin.pendingNotifications.pageInfo": "Sayfa {page} / {total}",
    "admin.pendingNotifications.toast.dispatched": "Bildirim gönderildi.",
    "admin.pendingNotifications.toast.dispatchFailed": "Gönderim başarısız.",
    "admin.pendingNotifications.toast.cancelled": "İptal edildi.",
    "admin.pendingNotifications.toast.cancelFailed": "İptal başarısız.",
  },
  en: {
    // --- ortak (admin geneli) ---------------------------------------------
    "admin.common.listError": "Failed to load the list.",
    "admin.common.noRecords": "No records.",
    "admin.common.recordCount": "{n} records",
    "admin.action.cancel": "Cancel",
    "admin.action.ok": "OK",
    "admin.field.name": "Name",
    "admin.field.slug": "Slug",
    "admin.field.plan": "Plan",
    "admin.field.automation": "Automation",
    "admin.field.email": "Email",
    "admin.error.superAdminRequired": "This action requires Super Admin permission.",
    "admin.error.invalidForm": "The form fields are invalid.",
    "admin.error.unexpected": "An unexpected error occurred.",
    "admin.error.notFound": "Organization not found.",

    // --- davet linki bloğu (create + invite paylaşır) ---------------------
    "admin.invite.linkLabel": "Invitation link",
    "admin.invite.copy": "Copy",
    "admin.invite.copied": "Link copied",
    "admin.invite.copyFailed": "Could not copy; select and copy manually.",
    "admin.invite.linkHelp": "Share this link with the invitee. Valid for 7 days.",
    "admin.invite.onlyOnce": "only once",

    // --- Kurumlar ---------------------------------------------------------
    "admin.tenants.forbidden.title": "Access denied",
    "admin.tenants.forbidden.desc":
      "The organization management page is available to Super Admin accounts only.",
    "admin.tenants.title": "Organizations",
    "admin.tenants.subtitle":
      "Super Admin view. Create, edit, invite, or soft-delete organizations.",
    "admin.tenants.new": "New organization",
    "admin.tenants.loadError": "Failed to load the organization list.",
    "admin.tenants.col.created": "Created",
    "admin.tenants.col.actions": "Actions",
    "admin.tenants.action.edit": "Edit",
    "admin.tenants.action.invite": "Invite",
    "admin.tenants.action.llm": "LLM settings",
    "admin.tenants.action.engagement": "Engagement bands",
    "admin.tenants.action.delete": "Delete",
    "admin.tenants.empty.title": "No organizations yet",
    "admin.tenants.empty.desc": "Create the first organization and send the admin invitation.",

    // --- engagement bands (super admin only) ------------------------------
    "admin.engagement.title": "Engagement Bands",
    "admin.engagement.desc":
      "{tenant} — define what each engagement-rate range means.",
    "admin.engagement.usingDefaults":
      "No custom bands defined for this organization yet; showing the defaults.",
    "admin.engagement.field.minPct": "Lower bound (%)",
    "admin.engagement.field.label": "Label",
    "admin.engagement.addBand": "Add band",
    "admin.engagement.removeBand": "Remove band",
    "admin.engagement.help":
      "Each band applies from its own lower bound up to the next one's. The first band starts at 0%; a rate exactly on a bound falls into the higher band.",
    "admin.engagement.save": "Save",
    "admin.engagement.saving": "Saving…",
    "admin.engagement.toast.saved": "Engagement bands updated.",
    "admin.engagement.toast.saveError": "Failed to save bands.",
    "admin.engagement.error.minPctRange":
      "The lower bound must be a number between 0 and 100.",
    "admin.engagement.error.labelRequired": "Label cannot be empty.",
    "admin.engagement.error.atLeastOne": "Define at least one band.",
    "admin.engagement.error.startsAtZero":
      "The first band's lower bound must be 0%.",
    "admin.engagement.error.ascending":
      "Lower bounds must be in ascending order and distinct.",

    // --- llm (per-organization model + API key management) ----------------
    "admin.llm.title": "AI Settings",
    "admin.llm.subtitle":
      "The organization's AI provider, model, and API keys. The topmost active row wins; the ones below are fallbacks in order.",
    "admin.llm.subtitleFor":
      "{tenant} — AI provider, model, and API keys. The topmost active row wins; the ones below are fallbacks in order.",
    "admin.llm.backToTenants": "Organizations",
    "admin.llm.loadError": "Failed to load keys.",
    "admin.llm.empty":
      "No keys added for this organization yet. Add the first one using the form below.",
    "admin.llm.primary": "Primary",
    "admin.llm.backup": "Backup {n}",
    "admin.llm.lastFailed": "Last failure: {date}",
    "admin.llm.warning": "caution",
    "admin.llm.toggleActive": "Enable/Disable",
    "admin.llm.editLabel": "Edit label",
    "admin.llm.dragHandle": "Reorder handle",
    "admin.llm.reorderFailed": "Failed to save the ordering.",
    "admin.llm.labelUpdateFailed": "Failed to update label.",
    "admin.llm.statusUpdateFailed": "Failed to update status.",
    "admin.llm.keyDeleted": "Key deleted.",
    "admin.llm.deleteFailed": "Delete failed.",
    "admin.llm.delete": "Delete",
    "admin.llm.add": "Add",
    "admin.llm.deleteAria": "Delete {label}",
    "admin.llm.deleteConfirmTitle": "Delete API key?",
    "admin.llm.deleteConfirmDesc":
      "will be permanently deleted. This action cannot be undone; the key remains valid on the provider's side, and you can add it again if you wish.",
    "admin.llm.addTitle": "Add new key",
    "admin.llm.labelField": "Label",
    "admin.llm.labelPlaceholder": "e.g. Primary Account",
    "admin.llm.apiKeyField": "API key",
    "admin.llm.hideKey": "Hide key",
    "admin.llm.showKey": "Show key",
    "admin.llm.keyPrefixWarning": "Gemini keys start with \"AIza\".",
    "admin.llm.orKeyPrefixWarning": "OpenRouter keys start with \"sk-or-\".",
    "admin.llm.keyAdded": "Key added.",
    "admin.llm.addFailed": "Failed to add key.",
    "admin.llm.providerField": "Provider",
    "admin.llm.modelField": "Model",
    "admin.llm.modelDefault": "Default model",
    "admin.llm.modelSearchPlaceholder": "Search models…",
    "admin.llm.modelRecommended": "Recommended",
    "admin.llm.modelAll": "All models",
    "admin.llm.modelEmpty": "No matching models.",
    "admin.llm.modelChanged": "Model updated.",
    "admin.llm.modelChangeFailed": "Failed to update model.",

    // --- LLM Denetimi -----------------------------------------------------
    "admin.llmAudit.callType.all": "All",
    "admin.llmAudit.callType.classification": "Classification",
    "admin.llmAudit.callType.briefing": "Briefing",
    "admin.llmAudit.callType.strategicReport": "Strategic report",
    "admin.llmAudit.callType.actionExtraction": "Action extraction",
    "admin.llmAudit.callType.okr": "OKR",
    "admin.llmAudit.title": "LLM Call Audit",
    "admin.llmAudit.subtitle":
      "Prompt hash + model meta + tokens + error record for every LLM call. Traceability of our AI decisions.",
    "admin.llmAudit.summary.totalCalls": "Last 30 days — total calls",
    "admin.llmAudit.summary.failures": "Failure count",
    "admin.llmAudit.summary.totalTokens": "Total tokens",
    "admin.llmAudit.dailyChart": "Daily tokens + calls",
    "admin.llmAudit.result.all": "All results",
    "admin.llmAudit.result.ok": "Successful only",
    "admin.llmAudit.result.fail": "Failures only",
    "admin.llmAudit.detail.prompt": "Prompt",
    "admin.llmAudit.detail.promptHash": "Prompt hash",
    "admin.llmAudit.detail.provider": "Provider",
    "admin.llmAudit.detail.tokensInOut": "Tokens (in/out)",
    "admin.llmAudit.detail.requestId": "Request id",
    "admin.llmAudit.detail.error": "Error",

    // --- Karar Geçmişi ----------------------------------------------------
    "admin.decisionAudit.title": "Decision History",
    "admin.decisionAudit.subtitle":
      "Timestamped record of manager decisions such as approvals, rejections, assignments, and goals.",
    "admin.decisionAudit.allTypes": "All decision types",
    "admin.decisionAudit.rationale": "Rationale:",
    "admin.decisionAudit.type.briefingAcknowledged": "Executive summary acknowledged",
    "admin.decisionAudit.type.briefingDismissed": "Executive summary dismissed",
    "admin.decisionAudit.type.strategicReportApproved": "Strategic report approved",
    "admin.decisionAudit.type.strategicReportRejected": "Strategic report rejected",
    "admin.decisionAudit.type.actionItemAssigned": "Action assigned",
    "admin.decisionAudit.type.actionItemPriorityChanged": "Action priority changed",
    "admin.decisionAudit.type.slaRuleChanged": "SLA rule changed",
    "admin.decisionAudit.type.kpiGoalSet": "KPI goal set",
    "admin.decisionAudit.type.webhookDispatchedManually": "Notification dispatched manually",
    "admin.decisionAudit.type.tenantSettingChanged": "Organization setting changed",
    "admin.decisionAudit.type.promptTemplateOverridden": "Prompt template overridden",

    // --- Prompt Şablonları ------------------------------------------------
    "admin.promptTemplates.title": "Prompt Templates",
    "admin.promptTemplates.subtitle":
      "System + user prompts for LLM calls. Copy the defaults to create an organization-specific template. The Test button runs Jinja2 on the server.",
    "admin.promptTemplates.defaultsError":
      "Failed to load default templates; only saved overrides are listed.",
    "admin.promptTemplates.badge.custom": "custom",
    "admin.promptTemplates.badge.default": "default",
    "admin.promptTemplates.selectPrompt": "Select a template from the left.",
    "admin.promptTemplates.override": "Organization-specific",
    "admin.promptTemplates.defaultLabel": "Default",
    "admin.promptTemplates.systemPrompt": "System prompt",
    "admin.promptTemplates.userPromptLabel": "User prompt template (Jinja2 — use {{ variable }})",
    "admin.promptTemplates.userPromptLockedHint":
      "In this template the comment list is assembled by the system — only the system instruction is editable.",
    "admin.promptTemplates.expectedVars": "Expected variables:",
    "admin.promptTemplates.updateOverride": "Update override",
    "admin.promptTemplates.createOverride": "Create organization override",
    "admin.promptTemplates.deleteConfirm":
      "Delete the override? The organization reverts to the default.",
    "admin.promptTemplates.deleteOverride": "Delete override",
    "admin.promptTemplates.testRun": "Test run",
    "admin.promptTemplates.variablesJson": "Variables (JSON)",
    "admin.promptTemplates.varsPlaceholder": '{"text": "example", "categories": ["a", "b"]}',
    "admin.promptTemplates.testButton": "Test",
    "admin.promptTemplates.running": "Running…",
    "admin.promptTemplates.virtualTestHint":
      "Test runs work on saved templates — create an override first.",
    "admin.promptTemplates.name.swot": "SWOT Analysis",
    "admin.promptTemplates.name.okr": "OKR Goals",
    "admin.promptTemplates.name.briefing": "Executive Summary",
    "admin.promptTemplates.name.unifiedClassifier": "Comment Classification",
    "admin.promptTemplates.toast.updated": "Override updated.",
    "admin.promptTemplates.toast.created": "Organization template created.",
    "admin.promptTemplates.toast.varsParseError": "Could not parse the variables JSON.",
    "admin.promptTemplates.toast.testOk": "Test successful ({source}).",
    "admin.promptTemplates.toast.deleted": "Override deleted.",

    // --- Kurum oluştur diyaloğu -------------------------------------------
    "admin.tenantCreate.title": "New organization",
    "admin.tenantCreate.desc":
      "Name and slug are required. Optionally, the first admin invitation can be created in the same step.",
    "admin.tenantCreate.slugHelp":
      "Shown in the URL. Only lowercase letters, digits, and hyphens. Cannot be changed later.",
    "admin.tenantCreate.seedAdminLabel": "Send the first admin invitation",
    "admin.tenantCreate.seedAdminHelp":
      "An invitation token is generated when the organization is created.",
    "admin.tenantCreate.fullName": "Full name",
    "admin.tenantCreate.create": "Create",
    "admin.tenantCreate.creating": "Creating...",
    "admin.tenantCreate.toast.createdTitle": "Organization created",
    "admin.tenantCreate.toast.createdInvite":
      "The first admin invitation is ready — share the link.",
    "admin.tenantCreate.toast.createError": "Could not create organization",
    "admin.tenantCreate.error.slugTaken": "This slug is already in use.",
    "admin.tenantCreate.success.aiSuggestNote":
      "After setup, have AI suggest categories from Settings → Taxonomies.",
    "admin.tenantCreate.step.next": "Next",
    "admin.tenantCreate.step.back": "Back",
    "admin.tenantCreate.step.skip": "Skip",
    "admin.tenantCreate.step.basicsShort": "Basics",
    "admin.tenantCreate.step.profileShort": "Profile",
    "admin.tenantCreate.step.inviteShort": "Invite",
    "admin.tenantCreate.step.profileDesc":
      "Optional — industry/size/description sharpen SWOT, OKR, and briefing output. Fully skippable.",
    "admin.tenantCreate.step.profileHelp":
      "This step is optional; leave it blank and continue with \"Skip\".",
    "admin.tenantCreate.success.title": "{name} created",
    "admin.tenantCreate.success.desc1":
      "The invitation link for the first admin is ready. This link is shown ",
    "admin.tenantCreate.success.desc2": " — share it before closing the modal.",
    "admin.tenantCreate.success.done": "Done, I shared it",

    // --- Kurum düzenle diyaloğu -------------------------------------------
    "admin.tenantEdit.title": "Edit organization",
    "admin.tenantEdit.desc":
      "The slug cannot be changed. You can update the name and the plan / automation settings.",
    "admin.tenantEdit.slugLabel": "Slug (immutable)",
    "admin.tenantEdit.save": "Save",
    "admin.tenantEdit.saving": "Saving...",
    "admin.tenantEdit.toast.updated": "Organization updated",
    "admin.tenantEdit.toast.updateError": "Could not update",

    // --- Kurum sil diyaloğu -----------------------------------------------
    "admin.tenantDelete.title": "Delete {name}",
    "admin.tenantDelete.desc":
      "You are about to delete this organization. All its data is soft-deleted; it can be restored at the database level if needed. Active users can no longer see this organization.",
    "admin.tenantDelete.delete": "Delete",
    "admin.tenantDelete.deleting": "Deleting...",
    "admin.tenantDelete.toast.deletedTitle": "Organization deleted",
    "admin.tenantDelete.toast.deletedDesc": "{name} archived (soft-delete).",
    "admin.tenantDelete.toast.deleteError": "Could not delete",
    "admin.tenantDelete.error.notFound": "The organization is already deleted or was not found.",

    // --- Kurum davet diyaloğu ---------------------------------------------
    "admin.tenantInvite.ready": "Invitation ready",
    "admin.tenantInvite.ready.desc1": "This link is shown ",
    "admin.tenantInvite.ready.desc2":
      " — share it with the invitee before closing the modal. Valid for 7 days.",
    "admin.tenantInvite.title": "Invite to {name}",
    "admin.tenantInvite.desc":
      "Choose the email to invite and the role. The token is shown only once, to share directly with the user.",
    "admin.tenantInvite.emailPlaceholder": "user@company.com",
    "admin.tenantInvite.role": "Role",
    "admin.tenantInvite.create": "Create invitation",
    "admin.tenantInvite.preparing": "Preparing...",
    "admin.tenantInvite.toast.readyDesc": "For {name}.",
    "admin.tenantInvite.toast.error": "Could not create invitation",
    "admin.tenantInvite.error.forbidden": "You don't have permission.",
    "admin.tenantInvite.error.duplicate": "There is already an open invitation for this email.",
    "admin.tenantInvite.error.invalidEmail": "The email is invalid.",

    // --- Bekleyen Bildirimler ---------------------------------------------
    "admin.pendingNotifications.title": "Pending Notifications",
    "admin.pendingNotifications.subtitle":
      "SLA notifications triggered in manual mode. Approve here to send to Slack/Teams channels, or cancel.",
    "admin.pendingNotifications.slaRules": "SLA rules",
    "admin.pendingNotifications.total": "Total {n}",
    "admin.pendingNotifications.tab.pending": "Pending",
    "admin.pendingNotifications.tab.sent": "Sent",
    "admin.pendingNotifications.tab.failed": "Failed",
    "admin.pendingNotifications.tab.dismissed": "Cancelled",
    "admin.pendingNotifications.tab.all": "All",
    "admin.pendingNotifications.noRuleName": "(no rule name)",
    "admin.pendingNotifications.retries": "{n} attempts",
    "admin.pendingNotifications.dispatch": "Send",
    "admin.pendingNotifications.cancel": "Cancel",
    "admin.pendingNotifications.status.pending": "Pending",
    "admin.pendingNotifications.status.sent": "Sent",
    "admin.pendingNotifications.status.failed": "Failed",
    "admin.pendingNotifications.status.dismissed": "Cancelled",
    "admin.pendingNotifications.empty.pending":
      "No pending notifications. They will appear here when an SLA breach occurs.",
    "admin.pendingNotifications.empty.filtered": "No records found for this filter.",
    "admin.pendingNotifications.prev": "Previous",
    "admin.pendingNotifications.next": "Next",
    "admin.pendingNotifications.pageInfo": "Page {page} / {total}",
    "admin.pendingNotifications.toast.dispatched": "Notification sent.",
    "admin.pendingNotifications.toast.dispatchFailed": "Dispatch failed.",
    "admin.pendingNotifications.toast.cancelled": "Cancelled.",
    "admin.pendingNotifications.toast.cancelFailed": "Cancellation failed.",
  },
};
