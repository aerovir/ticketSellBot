/**
 * TicketBot Mini App — main application logic.
 *
 * Telegram WebApp SDK integration:
 * - window.Telegram.WebApp.initData — raw initData for API auth
 * - window.Telegram.WebApp.HapticFeedback — haptic feedback
 * - window.Telegram.WebApp.MainButton — native main button
 * - CSS variables: --tg-theme-bg-color, --tg-theme-button-color, etc.
 */

// ─── State ──────────────────────────────────────────────────────
const state = {
    initData: "",
    events: [],
    currentEvent: null,
    tickets: [],
    lastAction: null, // function name for retry
};

// ─── Init ───────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
    // Init Telegram WebApp
    if (window.Telegram && window.Telegram.WebApp) {
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand(); // Expand to full height
        state.initData = tg.initData || "";
    } else {
        // Running outside Telegram (e.g., browser dev)
        state.initData = "";
        console.warn("Telegram WebApp SDK not found — running in dev mode");
    }

    // Check if opened with specific event_id
    const params = new URLSearchParams(window.location.search);
    const eventId = params.get("event_id");

    if (eventId) {
        await showEventDetail(eventId);
    } else {
        await showEvents();
    }
});

// ─── API helper ─────────────────────────────────────────────────

async function api(path, options = {}) {
    const headers = {
        "X-Init-Data": state.initData,
        ...options.headers,
    };

    // If X-Skip-Auth header works in dev, allow it
    if (!state.initData && window.location.hostname === "localhost") {
        headers["X-Skip-Auth"] = "1";
    }

    const resp = await fetch(path, {
        ...options,
        headers,
    });

    if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try {
            const err = await resp.json();
            detail = err.detail || detail;
        } catch {}
        throw new Error(detail);
    }

    return resp.json();
}

// ─── Navigation ─────────────────────────────────────────────────

function showPage(pageId) {
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
    const page = document.getElementById(`page-${pageId}`);
    if (page) page.classList.add("active");
    document.getElementById("loadingOverlay").classList.remove("active");
}

function updateToolbar(title, showBack = false, showTickets = true) {
    document.getElementById("toolbarTitle").textContent = title;
    document.getElementById("backBtn").style.display = showBack ? "inline-block" : "none";
    document.getElementById("myTicketsBtn").style.display = showTickets ? "inline-block" : "none";
}

// Back stack for simple navigation
const navStack = [];

function pushNav(page, data) {
    navStack.push({ page, data });
}

function goBack() {
    if (navStack.length > 0) {
        const prev = navStack.pop();
        if (prev.page === "events") showEvents();
        else if (prev.page === "event") showEventDetail(prev.data);
        else if (prev.page === "tickets") showMyTickets();
        else showEvents();
    } else {
        showEvents();
    }
}

// ─── Toast ──────────────────────────────────────────────────────

function showToast(message, isError = false) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = "toast active" + (isError ? " toast-error" : "");
    setTimeout(() => toast.classList.remove("active"), 3000);
}

// ─── Loading ────────────────────────────────────────────────────

function showLoading() {
    document.getElementById("loadingOverlay").classList.add("active");
}

function hideLoading() {
    document.getElementById("loadingOverlay").classList.remove("active");
}

// ═══════════════════════════════════════════════════════════════
// PAGE: Events List
// ═══════════════════════════════════════════════════════════════

async function showEvents() {
    state.lastAction = "showEvents";
    updateToolbar("TicketBot", false, true);
    showPage("events");
    showLoading();

    try {
        const events = await api("/api/events");
        state.events = events;
        renderEvents(events);
    } catch (err) {
        hideLoading();
        showEmpty("eventsContent", "😔 Нет предстоящих мероприятий");
    }
}

function renderEvents(events) {
    hideLoading();
    const container = document.getElementById("eventsContent");

    if (!events || events.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🎫</div>
                <h3>Нет предстоящих мероприятий</h3>
                <p>Следите за анонсами в нашем канале</p>
            </div>
        `;
        return;
    }

    let html = '<div class="events-list">';
    for (const e of events) {
        const dateStr = formatDate(e.date);
        const soldOut = e.available_tickets <= 0;
        html += `
            <div class="event-card" onclick="showEventDetail('${e.id}')">
                <div class="event-card-header">
                    <h3>${escapeHtml(e.title)}</h3>
                    ${soldOut ? '<span class="badge badge-soldout">Sold out</span>' : ''}
                </div>
                <div class="event-card-details">
                    <span class="event-info">📅 ${dateStr}</span>
                    ${e.location ? `<span class="event-info">📍 ${escapeHtml(e.location)}</span>` : ''}
                    <span class="event-info">💰 ${formatPrice(e.price)}</span>
                    <span class="event-info">🎟 ${e.available_tickets}/${e.total_tickets}</span>
                </div>
                ${!soldOut ? `<button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); showEventDetail('${e.id}')">🎟 Купить</button>` : ''}
            </div>
        `;
    }
    html += "</div>";
    container.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════════
// PAGE: Event Detail
// ═══════════════════════════════════════════════════════════════

async function showEventDetail(eventId) {
    state.lastAction = "showEventDetail";
    pushNav("events");
    showLoading();

    try {
        const event = await api(`/api/events/${eventId}`);
        state.currentEvent = event;
        renderEvent(event);
    } catch (err) {
        hideLoading();
        showError(err.message || "Мероприятие не найдено");
    }
}

function renderEvent(event) {
    hideLoading();
    updateToolbar(event.title, true, true);
    showPage("event");

    const container = document.getElementById("eventContent");
    const dateStr = formatDate(event.date);
    const soldOut = event.available_tickets <= 0;
    const passed = new Date(event.date) < new Date();

    let buyButton = "";
    if (passed) {
        buyButton = '<button class="btn btn-disabled" disabled>⏰ Мероприятие прошло</button>';
    } else if (soldOut) {
        buyButton = '<button class="btn btn-disabled" disabled>❌ Билеты закончились</button>';
    } else if (!event.is_active) {
        buyButton = '<button class="btn btn-disabled" disabled>🔴 Мероприятие отменено</button>';
    } else {
        buyButton = `<button class="btn btn-primary btn-lg" onclick="showConfirm('${event.id}')">🎟 Купить билет — ${formatPrice(event.price)}</button>`;
    }

    container.innerHTML = `
        <div class="event-detail">
            <h2>${escapeHtml(event.title)}</h2>
            ${event.description ? `<p class="event-description">${escapeHtml(event.description)}</p>` : ''}
            <div class="event-meta">
                <div class="meta-row"><span class="meta-label">📅 Дата</span><span>${dateStr}</span></div>
                <div class="meta-row"><span class="meta-label">📍 Место</span><span>${event.location || 'Не указано'}</span></div>
                <div class="meta-row"><span class="meta-label">💰 Цена</span><span>${formatPrice(event.price)}</span></div>
                <div class="meta-row"><span class="meta-label">🎟 Билетов</span><span>${event.available_tickets} из ${event.total_tickets}</span></div>
            </div>
            <div class="buy-section">
                ${buyButton}
            </div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// PAGE: Confirm Purchase
// ═══════════════════════════════════════════════════════════════

function showConfirm(eventId) {
    const event = state.currentEvent;
    if (!event || event.id !== eventId) return;

    updateToolbar("Подтверждение", true, false);
    showPage("confirm");

    const container = document.getElementById("confirmContent");
    container.innerHTML = `
        <div class="confirm-card">
            <h3>Подтверждение покупки</h3>
            <div class="confirm-details">
                <div class="confirm-row">
                    <span>Мероприятие</span>
                    <span><b>${escapeHtml(event.title)}</b></span>
                </div>
                <div class="confirm-row">
                    <span>Дата</span>
                    <span>${formatDate(event.date)}</span>
                </div>
                <div class="confirm-row">
                    <span>Цена</span>
                    <span><b>${formatPrice(event.price)}</b></span>
                </div>
            </div>
            <button class="btn btn-primary btn-lg" onclick="confirmBuy('${eventId}')" id="confirmBtn">
                ✅ Подтвердить покупку
            </button>
            <button class="btn btn-secondary" onclick="showEventDetail('${eventId}')">
                ← Отмена
            </button>
        </div>
    `;
}

async function confirmBuy(eventId) {
    const btn = document.getElementById("confirmBtn");
    btn.disabled = true;
    btn.textContent = "⏳ Оформление...";

    try {
        const result = await api(`/api/events/${eventId}/buy`, { method: "POST" });

        // Haptic feedback
        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback) {
            window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");
        }

        showSuccess(result);
    } catch (err) {
        btn.disabled = false;
        btn.textContent = "✅ Подтвердить покупку";
        showError(err.message || "Ошибка при покупке");
    }
}

// ═══════════════════════════════════════════════════════════════
// PAGE: Success
// ═══════════════════════════════════════════════════════════════

function showSuccess(result) {
    updateToolbar("Успешно!", false, true);
    showPage("success");
    document.getElementById("successTicketId").textContent = result.ticket_id || "—";
}

function copyTicketId() {
    const id = document.getElementById("successTicketId").textContent;
    if (!id || id === "—") return;

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(id);
    }
    showToast("✅ Номер скопирован");
}

// ═══════════════════════════════════════════════════════════════
// PAGE: My Tickets
// ═══════════════════════════════════════════════════════════════

async function showMyTickets() {
    state.lastAction = "showMyTickets";
    pushNav("tickets");
    updateToolbar("Мои билеты", true, false);
    showPage("tickets");
    showLoading();

    try {
        const tickets = await api("/api/tickets");
        state.tickets = tickets;
        renderTickets(tickets);
    } catch (err) {
        hideLoading();
        showError(err.message || "Ошибка загрузки билетов");
    }
}

function renderTickets(tickets) {
    hideLoading();
    const container = document.getElementById("ticketsContent");

    if (!tickets || tickets.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🎟</div>
                <h3>У вас нет билетов</h3>
                <button class="btn btn-primary" onclick="showEvents()">📋 К мероприятиям</button>
            </div>
        `;
        return;
    }

    let html = '<div class="tickets-list">';
    for (const t of tickets) {
        const dateStr = formatDate(t.purchase_date);
        const isActive = t.status === "active";
        const statusEmoji = isActive ? "✅" : "❌";
        const statusText = isActive ? "Активен" : "Возвращён";

        html += `
            <div class="ticket-card ${isActive ? '' : 'ticket-cancelled'}">
                <div class="ticket-header">
                    <span class="ticket-event">${escapeHtml(t.event_title)}</span>
                    <span class="ticket-status">${statusEmoji} ${statusText}</span>
                </div>
                <div class="ticket-meta">
                    <span>🆔 <code>${t.id}</code></span>
                    <span>📅 Куплен: ${dateStr}</span>
                </div>
                ${isActive ? `<button class="btn btn-danger btn-sm" onclick="cancelTicket('${t.id}')">↩️ Отменить</button>` : ''}
            </div>
        `;
    }
    html += "</div>";
    container.innerHTML = html;
}

async function cancelTicket(ticketId) {
    if (!confirm("Вы уверены, что хотите отменить билет?")) return;

    try {
        const result = await api(`/api/tickets/${ticketId}/cancel`, { method: "POST" });
        showToast("✅ Билет возвращён");
        await showMyTickets(); // Refresh
    } catch (err) {
        showError(err.message || "Ошибка при отмене");
    }
}

// ═══════════════════════════════════════════════════════════════
// PAGE: Error
// ═══════════════════════════════════════════════════════════════

function showError(message) {
    document.getElementById("errorMessage").textContent = message || "Произошла неизвестная ошибка";
    updateToolbar("Ошибка", true, false);
    showPage("error");

    // Haptic error feedback
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback) {
        window.Telegram.WebApp.HapticFeedback.notificationOccurred("error");
    }
}

function retryLastAction() {
    const action = state.lastAction;
    if (action && typeof window[action] === "function") {
        window[action]();
    } else {
        showEvents();
    }
}

// ═══════════════════════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════════════════════

function formatDate(isoStr) {
    if (!isoStr) return "—";
    const d = new Date(isoStr);
    const day = String(d.getDate()).padStart(2, "0");
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const year = d.getFullYear();
    const hours = String(d.getHours()).padStart(2, "0");
    const mins = String(d.getMinutes()).padStart(2, "0");
    return `${day}.${month}.${year} ${hours}:${mins}`;
}

function formatPrice(price) {
    if (price == null) return "—";
    return `${Math.round(Number(price))} ₽`;
}

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function showEmpty(containerId, message) {
    const container = document.getElementById(containerId);
    container.innerHTML = `
        <div class="empty-state">
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}
