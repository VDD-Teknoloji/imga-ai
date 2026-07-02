import type { Bundle } from "./types";

/** tickets alan sözlüğü (Sprint 12 i18n). */
export const tickets: Bundle = {
  tr: {
    // --- ortak ---
    "tickets.common.loading": "Yükleniyor…",
    "tickets.common.dismiss": "Vazgeç",
    "tickets.common.unassigned": "Atanmamış",
    "tickets.common.unknownUser": "Bilinmeyen kullanıcı",
    "tickets.common.archived": "Arşivlenmiş",
    "tickets.common.noMatch": "Eşleşme yok.",

    // --- liste ---
    "tickets.list.title": "Ticket'lar",
    "tickets.list.showing": "{shown} Ticket gösteriliyor / toplam {total}",
    "tickets.list.loadError": "Ticket'lar yüklenemedi.",
    "tickets.list.empty": "Henüz ticket yok.",
    "tickets.list.emptyFiltered": "Bu filtrelerle eşleşen ticket'ı yok.",
    "tickets.list.loadMore": "Daha fazla göster ({count} kaldı)",
    "tickets.list.colTitle": "Başlık",
    "tickets.list.colCategory": "Kategori",
    "tickets.list.colState": "Durum",
    "tickets.list.colPriority": "Öncelik",
    "tickets.list.colAssignee": "Atanan",
    "tickets.list.colUpdated": "Son güncelleme",
    "tickets.list.assigneeYou": "Sana",
    "tickets.list.assigneeOther": "Başka",

    // --- detay ---
    "tickets.detail.backToList": "Ticket listesi",
    "tickets.detail.loadError": "Ticket yüklenemedi.",
    "tickets.detail.state": "Durum",
    "tickets.detail.priority": "Öncelik",
    "tickets.detail.category": "Kategori",
    "tickets.detail.assignee": "Atanan",
    "tickets.detail.cancellationReason": "İptal sebebi",
    "tickets.detail.openedAt": "Açılış",
    "tickets.detail.resolvedAt": "Çözüm",
    "tickets.detail.closedAt": "Kapanış",
    "tickets.detail.customerReplyAt": "Müşteri yanıtı",

    // --- filtreler ---
    "tickets.filters.state": "Durum",
    "tickets.filters.priority": "Öncelik",
    "tickets.filters.category": "Kategori",
    "tickets.filters.assignee": "Atanan",
    "tickets.filters.assigneeMe": "Bana atananlar",
    "tickets.filters.assigneeAny": "Herkes",
    "tickets.filters.clear": "Filtreleri temizle",
    "tickets.filters.searchPlaceholder": "{label} ara...",

    // --- atama (dropdown) ---
    "tickets.assignee.you": "Sen",
    "tickets.assignee.loadError": "Kullanıcı listesi yüklenemedi.",
    "tickets.assignee.searchPlaceholder": "Kullanıcı ara...",
    "tickets.assignee.usersHeading": "Kullanıcılar",
    "tickets.assignee.adminOnly":
      "Sadece kurum yöneticisi başka kullanıcıya atayabilir.",

    // --- iptal (dialog) ---
    "tickets.cancel.title": "Ticket'ı iptal et",
    "tickets.cancel.description":
      "İptal sebebini seç. Bu kayıt timeline'da görünür ve metriklerde \"geçersiz\" olarak sayılır.",
    "tickets.cancel.reasonLabel": "Sebep",
    "tickets.cancel.reasonPlaceholder": "Sebep seç...",
    "tickets.cancel.submitting": "İptal ediliyor...",
    "tickets.cancel.submit": "İptal et",

    // --- bağlı analiz ---
    "tickets.linkedReview.title": "Bu Ticket'ı Açan Analiz",
    "tickets.linkedReview.viewDetail": "Detaylı Görüntüle",

    // --- yorumlar ---
    "tickets.comments.title": "Yorumlar",
    "tickets.comments.loadError": "Yorumlar yüklenemedi.",
    "tickets.comments.empty": "Henüz yorum yok.",
    "tickets.comments.archive": "Arşivle",
    "tickets.comments.archiveTitle": "Yorumu arşivle",
    "tickets.comments.archiveDescription":
      "Bu yorum arşivlenecek ve geri alınamaz. Yorum tarihçede görünmeye devam eder, üzeri çizili olarak gösterilir.",
    "tickets.comments.archiving": "Arşivleniyor...",
    "tickets.comments.placeholder": "Yorum yaz...",
    "tickets.comments.ariaBody": "Yorum metni",
    "tickets.comments.sending": "Gönderiliyor...",
    "tickets.comments.send": "Gönder",
    "tickets.comments.sendError":
      "Yorum gönderilemedi. Sayfayı yenileyip tekrar dene.",
    "tickets.comments.internalNote": "İç not",
    "tickets.comments.customerReply": "Müşteri yanıtı",
    "tickets.comments.terminalTooltip": "Kapalı ticket'a yanıt yazılamaz",
    "tickets.comments.roleTooltip": "Bu rol müşteri yanıtı yazamaz",

    // --- geçmiş (timeline) ---
    "tickets.timeline.title": "Geçmiş",
    "tickets.timeline.loadError": "Geçmiş yüklenemedi.",
    "tickets.timeline.empty": "Henüz aktivite yok.",
    "tickets.timeline.created": "Açıldı",
    "tickets.timeline.stateUpdated": "Durum güncellendi",
    "tickets.timeline.actorUser": "Kullanıcı",
    "tickets.timeline.actorSystem": "Sistem",
    "tickets.timeline.assignedBy": "{name} atadı",
    "tickets.timeline.assignedByUser": "Kullanıcı atadı",
    "tickets.timeline.assignedBySystem": "Sistem atadı",
  },
  en: {
    // --- common ---
    "tickets.common.loading": "Loading…",
    "tickets.common.dismiss": "Cancel",
    "tickets.common.unassigned": "Unassigned",
    "tickets.common.unknownUser": "Unknown user",
    "tickets.common.archived": "Archived",
    "tickets.common.noMatch": "No matches.",

    // --- list ---
    "tickets.list.title": "Tickets",
    "tickets.list.showing": "Showing {shown} of {total} tickets",
    "tickets.list.loadError": "Failed to load tickets.",
    "tickets.list.empty": "No tickets yet.",
    "tickets.list.emptyFiltered": "No tickets match these filters.",
    "tickets.list.loadMore": "Show more ({count} left)",
    "tickets.list.colTitle": "Title",
    "tickets.list.colCategory": "Category",
    "tickets.list.colState": "Status",
    "tickets.list.colPriority": "Priority",
    "tickets.list.colAssignee": "Assignee",
    "tickets.list.colUpdated": "Last updated",
    "tickets.list.assigneeYou": "You",
    "tickets.list.assigneeOther": "Other",

    // --- detail ---
    "tickets.detail.backToList": "Ticket list",
    "tickets.detail.loadError": "Failed to load ticket.",
    "tickets.detail.state": "Status",
    "tickets.detail.priority": "Priority",
    "tickets.detail.category": "Category",
    "tickets.detail.assignee": "Assignee",
    "tickets.detail.cancellationReason": "Cancellation reason",
    "tickets.detail.openedAt": "Opened",
    "tickets.detail.resolvedAt": "Resolved",
    "tickets.detail.closedAt": "Closed",
    "tickets.detail.customerReplyAt": "Customer reply",

    // --- filters ---
    "tickets.filters.state": "Status",
    "tickets.filters.priority": "Priority",
    "tickets.filters.category": "Category",
    "tickets.filters.assignee": "Assignee",
    "tickets.filters.assigneeMe": "Assigned to me",
    "tickets.filters.assigneeAny": "Everyone",
    "tickets.filters.clear": "Clear filters",
    "tickets.filters.searchPlaceholder": "Search {label}...",

    // --- assignee (dropdown) ---
    "tickets.assignee.you": "You",
    "tickets.assignee.loadError": "Failed to load user list.",
    "tickets.assignee.searchPlaceholder": "Search users...",
    "tickets.assignee.usersHeading": "Users",
    "tickets.assignee.adminOnly":
      "Only an organization admin can assign to other users.",

    // --- cancel (dialog) ---
    "tickets.cancel.title": "Cancel ticket",
    "tickets.cancel.description":
      "Choose a cancellation reason. This record appears in the timeline and counts as \"invalid\" in metrics.",
    "tickets.cancel.reasonLabel": "Reason",
    "tickets.cancel.reasonPlaceholder": "Select a reason...",
    "tickets.cancel.submitting": "Cancelling...",
    "tickets.cancel.submit": "Cancel ticket",

    // --- linked review ---
    "tickets.linkedReview.title": "Analysis That Opened This Ticket",
    "tickets.linkedReview.viewDetail": "View Details",

    // --- comments ---
    "tickets.comments.title": "Comments",
    "tickets.comments.loadError": "Failed to load comments.",
    "tickets.comments.empty": "No comments yet.",
    "tickets.comments.archive": "Archive",
    "tickets.comments.archiveTitle": "Archive comment",
    "tickets.comments.archiveDescription":
      "This comment will be archived and cannot be undone. It stays visible in the history, shown with a strikethrough.",
    "tickets.comments.archiving": "Archiving...",
    "tickets.comments.placeholder": "Write a comment...",
    "tickets.comments.ariaBody": "Comment text",
    "tickets.comments.sending": "Sending...",
    "tickets.comments.send": "Send",
    "tickets.comments.sendError":
      "Failed to send comment. Refresh the page and try again.",
    "tickets.comments.internalNote": "Internal Note",
    "tickets.comments.customerReply": "Customer reply",
    "tickets.comments.terminalTooltip": "Cannot reply to a closed ticket",
    "tickets.comments.roleTooltip": "This role cannot write customer replies",

    // --- timeline ---
    "tickets.timeline.title": "History",
    "tickets.timeline.loadError": "Failed to load history.",
    "tickets.timeline.empty": "No activity yet.",
    "tickets.timeline.created": "Opened",
    "tickets.timeline.stateUpdated": "Status updated",
    "tickets.timeline.actorUser": "User",
    "tickets.timeline.actorSystem": "System",
    "tickets.timeline.assignedBy": "Assigned by {name}",
    "tickets.timeline.assignedByUser": "Assigned by a user",
    "tickets.timeline.assignedBySystem": "Assigned by system",
  },
};
