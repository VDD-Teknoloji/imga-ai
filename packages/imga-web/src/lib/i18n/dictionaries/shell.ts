import type { Bundle } from "./types";

/** shell alan sözlüğü (Sprint 12 i18n) — navigasyon + uygulama kabuğu. */
export const shell: Bundle = {
  tr: {
    // Navigasyon (nav-config.ts label/heading/subgroup = i18n anahtarı;
    // sidebar-nav.tsx render sırasında t() ile çözer).
    "shell.nav.mainMenu": "Ana menü",
    "shell.nav.sectionAria": "{name} bölümü",
    "shell.nav.subgroupAria": "{name} alt grubu",
    "shell.nav.dashboard": "Panel",
    "shell.nav.executiveSummary": "Yönetici Özeti",
    "shell.nav.actionItems": "Aksiyonlar",
    "shell.nav.trendAlerts": "Uyarılar",
    "shell.nav.strategy": "Strateji",
    "shell.nav.insights": "İçgörüler",
    "shell.nav.reviewArchive": "Analiz Arşivi",
    "shell.nav.reports": "Raporlar",
    "shell.nav.tickets": "Ticket'lar",
    "shell.nav.manualAnalysis": "Manuel Analiz",
    "shell.nav.batchUpload": "Toplu Yükleme",
    "shell.nav.twitterImport": "Twitter'dan Çek",
    "shell.nav.settings": "Ayarlar",
    "shell.nav.subgroup.dataUpload": "Veri Yükle",
    "shell.nav.section.analytics": "Analitik",
    "shell.nav.section.operations": "Operasyon",
    "shell.nav.section.admin": "Yönetim",
    "shell.nav.tenants": "Kurumlar",
    "shell.nav.llmAudit": "LLM Denetimi",
    "shell.nav.decisionAudit": "Karar Geçmişi",
    "shell.nav.promptTemplates": "Prompt Şablonları",
    "shell.nav.pendingWebhooks": "Bekleyen Bildirimler",

    // Üst çubuk (mobil).
    "shell.header.openMenu": "Menüyü aç",

    // Kenar çubuğu.
    "shell.sidebar.label": "Kenar çubuğu",
    "shell.sidebar.collapse": "Kenar çubuğunu daralt",
    "shell.sidebar.expand": "Kenar çubuğunu genişlet",

    // Hızlı işlem butonu (FAB).
    "shell.fab.title": "Hızlı işlemler",
    "shell.fab.open": "Hızlı işlemleri aç",
    "shell.fab.close": "Hızlı işlemleri kapat",
    "shell.fab.newUpload.label": "Yeni yükleme",
    "shell.fab.newUpload.hint": "CSV / Excel toplu analiz",
    "shell.fab.executiveSummary.label": "Yönetici Özeti",
    "shell.fab.executiveSummary.hint": "Aylık yönetici özeti",
    "shell.fab.actionItems.label": "Aksiyonlar",
    "shell.fab.actionItems.hint": "Bekleyen aksiyonlar",
    "shell.fab.strategy.label": "Strateji raporu",
    "shell.fab.strategy.hint": "SWOT / OKR",

    // Kurum değiştirici.
    "shell.tenant.none": "Kurum seçilmedi",
    "shell.tenant.switched": "Kurum değiştirildi",
    "shell.tenant.switchFailed": "Kurum değiştirilemedi",
    "shell.tenant.triggerAria": "Aktif kurum: {name}. Değiştirmek için açın.",
    "shell.tenant.searchPlaceholder": "Kurum ara...",
    "shell.tenant.empty": "Eşleşen kurum yok.",
    "shell.tenant.available": "Mevcut kurumlar",
    "shell.tenant.acceptInvite": "Yeni davet kabul et",

    // Kullanıcı menüsü.
    "shell.user.menuAria": "Kullanıcı menüsü: {name}",
    "shell.user.signOut": "Çıkış yap",
    "shell.user.logoutError": "Çıkış sırasında hata oluştu",

    // Davet kabul modalı.
    "shell.invite.desc":
      "Davet linkindeki token'ı yapıştır, mevcut hesabınla yeni kuruma katıl.",
    "shell.invite.tokenLabel": "Davet token'ı",
    "shell.invite.checking": "Davet kontrol ediliyor...",
    "shell.invite.invalidToken":
      "Bu token geçersiz, süresi dolmuş veya kullanılmış.",
    "shell.invite.otherEmailInline":
      "⚠ Davet bu hesap için değil. Kabul edilmeyecek.",
    "shell.invite.passwordLabel": "Şifren",
    "shell.invite.passwordHelp":
      "Güvenlik için yeni kuruma katılırken şifrenle doğrulan.",
    "shell.invite.otherEmailTitle": "Bu davet farklı bir e-posta için",
    "shell.invite.otherEmailDesc":
      "Davet {email} için. Bu modal sadece kendi davetlerini kabul etmek içindir.",
    "shell.invite.acceptedTitle": "Davet kabul edildi",
    "shell.invite.acceptedDesc": "{name} artık kurum listende.",
    "shell.invite.acceptFailedTitle": "Davet kabul edilemedi",
    "shell.invite.cancel": "Vazgeç",
    "shell.invite.submitting": "Kabul ediliyor...",
    "shell.invite.submit": "Daveti kabul et",
    "shell.invite.err401": "Şifre hatalı.",
    "shell.invite.err403": "Bu davet farklı bir e-posta için.",
    "shell.invite.err404":
      "Davet geçersiz, süresi dolmuş veya zaten kullanılmış.",
    "shell.invite.errGeneric": "Beklenmeyen bir hata oluştu.",
  },
  en: {
    // Navigation.
    "shell.nav.mainMenu": "Main menu",
    "shell.nav.sectionAria": "{name} section",
    "shell.nav.subgroupAria": "{name} subgroup",
    "shell.nav.dashboard": "Dashboard",
    "shell.nav.executiveSummary": "Executive Summary",
    "shell.nav.actionItems": "Action Items",
    "shell.nav.trendAlerts": "Alerts",
    "shell.nav.strategy": "Strategy",
    "shell.nav.insights": "Insights",
    "shell.nav.reviewArchive": "Analysis Archive",
    "shell.nav.reports": "Reports",
    "shell.nav.tickets": "Tickets",
    "shell.nav.manualAnalysis": "Manual Analysis",
    "shell.nav.batchUpload": "Batch Upload",
    "shell.nav.twitterImport": "Import from Twitter",
    "shell.nav.settings": "Settings",
    "shell.nav.subgroup.dataUpload": "Upload Data",
    "shell.nav.section.analytics": "Analytics",
    "shell.nav.section.operations": "Operations",
    "shell.nav.section.admin": "Administration",
    "shell.nav.tenants": "Organizations",
    "shell.nav.llmAudit": "LLM Audit",
    "shell.nav.decisionAudit": "Decision History",
    "shell.nav.promptTemplates": "Prompt Templates",
    "shell.nav.pendingWebhooks": "Pending Webhooks",

    // Top bar (mobile).
    "shell.header.openMenu": "Open menu",

    // Sidebar.
    "shell.sidebar.label": "Sidebar",
    "shell.sidebar.collapse": "Collapse sidebar",
    "shell.sidebar.expand": "Expand sidebar",

    // Quick action button (FAB).
    "shell.fab.title": "Quick actions",
    "shell.fab.open": "Open quick actions",
    "shell.fab.close": "Close quick actions",
    "shell.fab.newUpload.label": "New upload",
    "shell.fab.newUpload.hint": "Bulk CSV / Excel analysis",
    "shell.fab.executiveSummary.label": "Executive Summary",
    "shell.fab.executiveSummary.hint": "Monthly executive summary",
    "shell.fab.actionItems.label": "Action Items",
    "shell.fab.actionItems.hint": "Pending action items",
    "shell.fab.strategy.label": "Strategy report",
    "shell.fab.strategy.hint": "SWOT / OKR",

    // Organization switcher.
    "shell.tenant.none": "No organization selected",
    "shell.tenant.switched": "Organization changed",
    "shell.tenant.switchFailed": "Could not change organization",
    "shell.tenant.triggerAria":
      "Active organization: {name}. Open to change.",
    "shell.tenant.searchPlaceholder": "Search organizations...",
    "shell.tenant.empty": "No matching organization.",
    "shell.tenant.available": "Your organizations",
    "shell.tenant.acceptInvite": "Accept new invitation",

    // User menu.
    "shell.user.menuAria": "User menu: {name}",
    "shell.user.signOut": "Sign out",
    "shell.user.logoutError": "An error occurred while signing out",

    // Invitation accept dialog.
    "shell.invite.desc":
      "Paste the token from your invitation link and join the new organization with your existing account.",
    "shell.invite.tokenLabel": "Invitation token",
    "shell.invite.checking": "Checking invitation...",
    "shell.invite.invalidToken":
      "This token is invalid, expired, or already used.",
    "shell.invite.otherEmailInline":
      "⚠ This invitation isn't for this account. It won't be accepted.",
    "shell.invite.passwordLabel": "Your password",
    "shell.invite.passwordHelp":
      "For security, confirm with your password when joining a new organization.",
    "shell.invite.otherEmailTitle": "This invitation is for a different email",
    "shell.invite.otherEmailDesc":
      "The invitation is for {email}. This dialog is only for accepting your own invitations.",
    "shell.invite.acceptedTitle": "Invitation accepted",
    "shell.invite.acceptedDesc": "{name} is now in your organization list.",
    "shell.invite.acceptFailedTitle": "Could not accept invitation",
    "shell.invite.cancel": "Cancel",
    "shell.invite.submitting": "Accepting...",
    "shell.invite.submit": "Accept invitation",
    "shell.invite.err401": "Incorrect password.",
    "shell.invite.err403": "This invitation is for a different email.",
    "shell.invite.err404":
      "The invitation is invalid, expired, or already used.",
    "shell.invite.errGeneric": "An unexpected error occurred.",
  },
};
