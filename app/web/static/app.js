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
    // Личный кабинет / админка
    me: null,
    role: "user",
    adminEvents: [],
    currentAdminEvent: null,
    adminChannels: [],
    globalStats: null,
    adminTab: "events",
};

// ═══════════════════════════════════════════════════════════════
// Telegram PopUp API (замена нативных confirm/prompt)
//
// Нативные confirm()/prompt() НЕ работают в Telegram WebView — диалог
// не показывается, функция молча возвращает false. Используем
// window.Telegram.WebApp.showPopup / showAlert, с fallback на
// confirm/prompt вне Telegram (браузер/dev).
// ═══════════════════════════════════════════════════════════════

function tgShowPopup(title, message, buttons) {
    // buttons: [{id, type, text}] — type: default/ok/cancel/close/destructive
    return new Promise(resolve => {
        const tg = window.Telegram && window.Telegram.WebApp;
        if (tg && tg.showPopup) {
            tg.showPopup({
                title: title || "TicketBot",
                message: message || "",
                buttons: buttons || [{ type: "close" }],
            }, (buttonId) => resolve(buttonId));
        } else {
            // fallback: последняя кнопка = подтверждение
            const last = buttons && buttons.length ? buttons[buttons.length - 1] : null;
            resolve(last ? last.id : null);
        }
    });
}

function tgConfirm(message, okText = "OK", cancelText = "Отмена") {
    return new Promise(resolve => {
        const tg = window.Telegram && window.Telegram.WebApp;
        if (tg && tg.showPopup) {
            tg.showPopup({
                title: "Подтверждение",
                message: message,
                buttons: [
                    { id: "cancel", type: "cancel", text: cancelText },
                    { id: "ok", type: "ok", text: okText },
                ],
            }, (buttonId) => resolve(buttonId === "ok"));
        } else {
            // Вне Telegram — нативный confirm
            resolve(window.confirm(message));
        }
    });
}

function tgPrompt(message, defaultValue = "") {
    return new Promise(resolve => {
        const tg = window.Telegram && window.Telegram.WebApp;
        if (tg && tg.showPopup) {
            // Telegram PopUp не поддерживает ввод текста. Показываем подсказку,
            // что ввод через popup невозможен — возвращаем null (отмена).
            tg.showPopup({
                title: "Ввод не поддерживается",
                message: message + "\n\nВвод текста недоступен в Telegram Mini App. " +
                    "Пожалуйста, используйте поле ввода рядом.",
                buttons: [{ id: "close", type: "close", text: "Ок" }],
            }, () => resolve(null));
        } else {
            resolve(window.prompt(message, defaultValue));
        }
    });
}

function tgAlert(message) {
    return new Promise(resolve => {
        const tg = window.Telegram && window.Telegram.WebApp;
        if (tg && tg.showAlert) {
            tg.showAlert({ message: message }, () => resolve());
        } else {
            window.alert(message);
            resolve();
        }
    });
}

// ─── Init ───────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
    // Init Telegram WebApp
    if (window.Telegram && window.Telegram.WebApp) {
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand(); // Expand to full height
        state.initData = tg.initData || "";
    } else {
        // Telegram Desktop (и некоторые клиенты) открывают Mini App как
        // обычную страницу и передают данные в URL-хэше: #tgWebAppData=...
        // SDK (window.Telegram) в этом случае не внедряется, но данные есть.
        state.initData = extractInitDataFromUrl() || "";
        if (!state.initData) {
            console.warn("Telegram WebApp SDK not found — running in dev mode");
        }
    }

    // Если initData пуст — кабинет открыт вне Telegram (не как Mini App).
    // Показываем понятное сообщение вместо пустого списка.
    if (!state.initData && window.location.hostname !== "localhost") {
        showNoInitData();
        return;
    }

    // Загружаем профиль/роль и строим таб-бар (best-effort: не блокируем покупку)
    try {
        await loadMe();
        renderTabBar();
    } catch (e) {
        console.warn("loadMe failed", e);
    }

    // Check if opened with specific event_id
    const params = new URLSearchParams(window.location.search);
    const eventId = params.get("event_id");

    if (eventId) {
        await showEventDetail(eventId);
    } else {
        await showHome();
    }
});

// ═══════════════════════════════════════════════════════════════
// Личный кабинет / роль
// ═══════════════════════════════════════════════════════════════

async function loadMe() {
    const me = await api("/api/me");
    state.me = me;
    state.role = me.role || "user";
    return me;
}

// Есть ли у организатора pro-подписка (пользователь или хотя бы один канал pro)?
function isPro() {
    if (!state.me) return false;
    if (state.me.subscription_tier === "pro") return true;
    // организатор с pro-каналом
    if ((state.me.channels || []).some(c => c.subscription_tier === "pro")) return true;
    return false;
}

function extractInitDataFromUrl() {
    // Telegram Desktop передаёт initData в фрагменте URL: #tgWebAppData=...
    // Это тот же initData, что mobile отдаёт через window.Telegram.WebApp.initData.
    try {
        const fragment = window.location.hash || "";
        if (!fragment.includes("tgWebAppData=")) return "";
        const params = new URLSearchParams(fragment.startsWith("#") ? fragment.slice(1) : fragment);
        return params.get("tgWebAppData") || "";
    } catch (e) {
        console.warn("extractInitDataFromUrl failed", e);
        return "";
    }
}

function showNoInitData() {
    // Кабинет открыт вне Telegram Mini App — initData недоступен.
    updateToolbar("TicketBot", false, false);
    showPage("events");

    // Диагностика причины: есть ли Telegram SDK, что в initDataUnsafe
    let diag = "window.Telegram: " + (window.Telegram ? "есть" : "нет");
    if (window.Telegram && window.Telegram.WebApp) {
        const tg = window.Telegram.WebApp;
        diag += "<br>WebApp: есть, initData len=" + (tg.initData ? tg.initData.length : 0);
        const u = (tg.initDataUnsafe && tg.initDataUnsafe.user) || {};
        diag += ", user.id=" + (u.id ?? "—");
    } else {
        diag += "<br>WebApp: НЕТ";
    }
    diag += "<br>URL: " + window.location.href;

    document.getElementById("eventsContent").innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">⚠️</div>
            <h3>Откройте кабинет в Telegram</h3>
            <p>Личный кабинет работает только внутри Telegram Mini App.<br>
            Откройте чат с ботом и нажмите кнопку <b>«Мероприятия»</b> внизу,
            либо кнопку <b>«🎫 Открыть кабинет»</b> в анонсах канала.</p>
            <div style="font-size:11px;color:#999;margin-top:16px;word-break:break-all">${diag}</div>
        </div>
    `;
}

function renderTabBar() {
    const bar = document.getElementById("tabBar");
    if (!bar || !state.me) {
        if (bar) bar.style.display = "none";
        return;
    }
    bar.style.display = "flex";
}

function setActiveTab(tabId) {
    document.querySelectorAll("#tabBar .tab").forEach(b => {
        b.classList.toggle("active", b.dataset.tab === tabId);
    });
}

// ═══════════════════════════════════════════════════════════════
// PAGE: Home Dashboard
// ═══════════════════════════════════════════════════════════════

async function showHome() {
    if (!state.me) { try { await loadMe(); } catch (e) { showError("Не удалось загрузить профиль"); return; } }
    setActiveTab("home");
    updateHeader("TicketBot");
    showPage("home");
    showLoading();

    try {
        const [events, tickets] = await Promise.all([
            api("/api/events").catch(() => []),
            api("/api/tickets").catch(() => []),
        ]);
        state.events = events;
        state.tickets = tickets;
    } catch (e) { /* не критично */ }

    hideLoading();
    renderHomeDashboard();
}

function renderHomeDashboard() {
    const container = document.getElementById("homeContent");
    const me = state.me || {};
    const isOrganizer = state.role !== "user";
    const isSuper = state.role === "super_admin";

    const events = state.events || [];
    const tickets = state.tickets || [];
    const channels = me.channels || [];

    let cards = [
        { icon: "🎫", value: events.length, label: "Мероприятий", onclick: "showAdminEvents()" },
        { icon: "🎟", value: tickets.length, label: "Билетов", onclick: "showMyTickets()" },
    ];

    if (isOrganizer) {
        cards.push({ icon: "📢", value: channels.length, label: "Каналов", onclick: "showMyChannels()" });
        cards.push({ icon: "🔍", value: "Вход", label: "Проверка билета", onclick: "showCheckin()" });
    }

    if (isSuper) {
        cards.push({ icon: "👥", value: "—", label: "Пользователи", onclick: "showAdminUserList()" });
        cards.push({ icon: "📊", value: "—", label: "Статистика", onclick: "showAdminStats()" });
    }

    let html = `<h2 style="padding:16px 16px 0">Привет, ${escapeHtml(me.name || 'Гость')}!</h2>`;
    html += `<p style="padding:0 16px 12px;color:var(--tg-hint)">${roleLabel(state.role)}</p>`;
    html += `<div class="dashboard-grid">`;
    for (const c of cards) {
        html += `
            <div class="dashboard-card" onclick="${c.onclick}">
                <div class="dashboard-card-icon">${c.icon}</div>
                <div class="dashboard-card-value">${c.value}</div>
                <div class="dashboard-card-label">${c.label}</div>
            </div>`;
    }
    html += `</div>`;

    // Список мероприятий на главной
    if (events.length > 0) {
        html += `<div class="section-header">📋 Ближайшие мероприятия</div>`;
        for (const e of events.slice(0, 3)) {
            html += `
                <div class="event-card" style="margin:0 16px 8px" onclick="showEventDetail('${e.id}')">
                    <h3>${escapeHtml(e.title)}</h3>
                    <div class="hint">📅 ${formatDate(e.date)} · ${e.price > 0 ? formatPrice(e.price) : 'Бесплатно'} · ${e.available_tickets}/${e.total_tickets}</div>
                </div>`;
        }
    }

    container.innerHTML = html;
}

function roleLabel(role) {
    const labels = { user: "Покупатель", organizer: "Организатор", super_admin: "Супер-админ" };
    return labels[role] || role;
}

function updateHeader(title) {
    document.getElementById("headerTitle").textContent = title;
}

async function showAdminUserList() {
    setActiveTab("home");
    updateHeader("Пользователи");
    try {
        const users = await api("/api/admin/users");
        let html = `<h2 style="padding:16px">👥 Пользователи (${users.length})</h2>`;
        for (const u of users) {
            html += `<div class="event-card" style="margin:0 16px 8px">
                <div><b>${escapeHtml(u.name || u.telegram_user_id)}</b></div>
                <div class="hint">ID: ${escapeHtml(u.telegram_user_id)} · ${u.subscription_tier}</div>
            </div>`;
        }
        document.getElementById("homeContent").innerHTML = html;
    } catch (e) { showToast(e.message, true); }
}

async function showProfile() {
    if (!state.me) { try { await loadMe(); } catch (e) { showError("Не удалось загрузить профиль"); return; } }
    setActiveTab("profile");
    updateToolbar("Профиль", false, false);
    showPage("profile");
    renderProfile();
}

function renderProfile() {
    const me = state.me;
    const roleNames = { user: "Покупатель", organizer: "Организатор", super_admin: "Супер-админ" };
    const roleText = roleNames[me.role] || me.role;
    const channels = me.channels || [];

    document.getElementById("profileContent").innerHTML = `
        <div class="profile-card">
            <div class="profile-avatar">👤</div>
            <h2>${escapeHtml(me.name || "Пользователь")}</h2>
            <p class="hint">Telegram ID: <code>${escapeHtml(me.telegram_user_id)}</code></p>
            <span class="badge badge-role">${roleText}</span>
            <button class="btn btn-sm btn-secondary" style="margin-top:12px" onclick="editName()">✏️ Изменить имя</button>
        </div>
        <h3 style="margin:20px 0 10px">Мои каналы</h3>
        ${channels.length === 0
            ? '<p class="hint">Нет каналов</p>'
            : `<div class="admin-list">
                ${channels.map(ch => `
                    <div class="admin-list-item">
                        <div><b>${escapeHtml(ch.title || ch.telegram_channel_id)}</b>
                            <span class="badge ${ch.subscription_tier === 'pro' ? 'badge-tier-pro' : 'badge-tier-basic'}">${ch.subscription_tier}</span>
                        </div>
                        <div class="hint">${ch.is_subscription_active ? '🟢 Активна' : '🔴 Неактивна'}${ch.subscription_until ? ' до ' + formatDate(ch.subscription_until) : ''}</div>
                    </div>`).join('')}
            </div>`}
        <button class="btn btn-secondary" style="margin-top:16px" onclick="showMyTickets()">🎫 Мои билеты</button>
    `;
}

async function editName() {
    const me = state.me;
    const newName = prompt("Ваше имя:", me.name || "");
    if (newName === null) return;  // отмена
    const name = newName.trim();
    if (!name) { showToast("Имя не может быть пустым", true); return; }
    try {
        await api("/api/me", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
        });
        showToast("✅ Имя обновлено");
        await loadMe();
        renderProfile();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

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
    updateHeader(title);
    // Legacy toolbar elements — скрыты в новом дизайне
    const tb = document.getElementById("toolbarTitle");
    if (tb) tb.textContent = title;
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
    setActiveTab("events");
    updateToolbar("Мероприятия", false, false);
    // Организаторы видят свои мероприятия с управлением, покупатели — публичную ленту
    if (state.role !== "user") {
        await showAdminEvents();
        return;
    }
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
                <button class="btn btn-primary" onclick="showAdminEventForm()">+ Создать мероприятие</button>
            </div>
        `;
        return;
    }

    let html = '<button class="btn btn-primary" onclick="showAdminEventForm()">+ Создать мероприятие</button>';
    html += '<div class="events-list" style="margin-top:12px">';
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
    setActiveTab("tickets");
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
    if (!(await tgConfirm("Вы уверены, что хотите отменить билет?"))) return;

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

// ═══════════════════════════════════════════════════════════════
// Админка
// ═══════════════════════════════════════════════════════════════

function showAdminDashboard() {
    setActiveTab("admin");
    updateToolbar("Панель", false, false);
    showPage("admin");
    const isSuper = state.role === "super_admin";
    const isOrganizer = state.role !== "user";  // organizer или super_admin
    document.getElementById("adminContent").innerHTML = `
        <h2 style="margin-bottom:16px">Панель управления</h2>
        <div class="admin-menu-grid">
            <button class="admin-menu-card" onclick="showAdminEvents()">
                <div class="admin-menu-icon">🎫</div>
                <div>Мероприятия</div>
            </button>
            ${isOrganizer ? `
            <button class="admin-menu-card" onclick="showCheckin()">
                <div class="admin-menu-icon">🔍</div>
                <div>Проверка билета</div>
            </button>` : ''}
            <button class="admin-menu-card" onclick="showMyChannels()">
                <div class="admin-menu-icon">📢</div>
                <div>Мои каналы</div>
            </button>
            ${isSuper ? `
            <button class="admin-menu-card" onclick="showAdminChannels()">
                <div class="admin-menu-icon">📋</div>
                <div>Все каналы</div>
            </button>
            <button class="admin-menu-card" onclick="showAdminStats()">
                <div class="admin-menu-icon">📊</div>
                <div>Статистика</div>
            </button>
            <button class="admin-menu-card" onclick="showBroadcast()">
                <div class="admin-menu-icon">📣</div>
                <div>Рассылка</div>
            </button>
            <button class="admin-menu-card" onclick="showUserInfo()">
                <div class="admin-menu-icon">👥</div>
                <div>Инфо о юзере</div>
            </button>
            <button class="admin-menu-card" onclick="showAdminHealth()">
                <div class="admin-menu-icon">🩺</div>
                <div>Здоровье</div>
            </button>` : ''}
        </div>
    `;
}

// ─── Мероприятия (список + создание) ───────────────────────────

async function showAdminEvents() {
    setActiveTab("admin");
    state.lastAction = "showAdminEvents";
    updateToolbar("Мероприятия", true, false);
    showPage("admin-events");
    showLoading();
    try {
        const events = await api("/api/admin/events");
        state.adminEvents = events;
        renderAdminEvents(events);
    } catch (err) {
        hideLoading();
        showError(err.message || "Ошибка загрузки мероприятий");
    }
}

function renderAdminEvents(events) {
    hideLoading();
    const container = document.getElementById("adminEventsContent");
    if (!events || events.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🎫</div>
                <h3>Нет мероприятий</h3>
                <button class="btn btn-primary" onclick="showAdminEventForm()">+ Создать мероприятие</button>
            </div>
        `;
        return;
    }
    container.innerHTML = `
        <button class="btn btn-primary" onclick="showAdminEventForm()">+ Создать мероприятие</button>
        <div class="admin-list" style="margin-top:12px">
            ${events.map(e => `
                <div class="admin-list-item">
                    <div style="flex:1;cursor:pointer" onclick="showAdminEventDetail('${e.id}')">
                        <div><b>${escapeHtml(e.title)}</b>
                            ${e.is_published ? '<span class="badge badge-published">опубл.</span>' : '<span class="badge badge-draft">черновик</span>'}
                            ${e.is_active ? '' : '<span class="badge badge-off">выкл</span>'}
                        </div>
                        <div class="hint">${formatDate(e.date)}${e.channel_title ? ' · ' + escapeHtml(e.channel_title) : ''} · ${e.price > 0 ? formatPrice(e.price) : 'Бесплатно'} · ${e.available_tickets}/${e.total_tickets}</div>
                    </div>
                    <button class="btn btn-sm btn-secondary" onclick="showAdminEventDetail('${e.id}')">Открыть</button>
                </div>`).join('')}
        </div>
    `;
}

async function showAdminEventForm(eventId) {
    updateToolbar(eventId ? "Редактировать" : "Создать мероприятие", true, false);
    showPage("admin-event-form");
    const container = document.getElementById("adminEventFormContent");

    let event = null;
    if (eventId) {
        try { event = await api(`/api/admin/events/${eventId}`); }
        catch (e) { showError(e.message || "Ошибка загрузки"); return; }
    }

    const me = state.me || {};
    const myChannels = me.channels || [];
    const options = myChannels.map(c => {
        const hasSub = c.is_subscription_active;
        return `<option value="${c.id}">${escapeHtml(c.title || c.telegram_channel_id)}${hasSub ? '' : ' (нет подписки)'}</option>`;
    }).join('');

    const dateVal = event ? toLocalInputValue(event.date) : "";

    container.innerHTML = `
        <form onsubmit="event.preventDefault(); submitAdminEventForm('${eventId || ''}')">
            <div class="form-field">
                <label class="form-label">Название *</label>
                <input class="form-input" id="f_title" required value="${escapeHtml(event ? event.title : '')}">
            </div>
            <div class="form-field">
                <label class="form-label">Описание</label>
                <textarea class="form-input" id="f_description">${escapeHtml(event ? (event.description || '') : '')}</textarea>
            </div>
            <div class="form-field">
                <label class="form-label">Дата и время *</label>
                <input class="form-input" type="datetime-local" id="f_date" required value="${dateVal}">
            </div>
            <div class="form-field">
                <label class="form-label">Место</label>
                <input class="form-input" id="f_location" value="${escapeHtml(event ? (event.location || '') : '')}">
            </div>
            <div class="form-field">
                <label class="form-label">Цена (₽, 0 = бесплатно)${isPro() ? '' : ' — только бесплатные на вашем тарифе'}</label>
                <input class="form-input" type="number" min="0" step="0.01" id="f_price" value="${event ? event.price : 0}" ${isPro() ? '' : 'disabled'}>
            </div>
            <div class="form-field">
                <label class="form-label">Количество билетов *</label>
                <input class="form-input" type="number" min="1" step="1" id="f_tickets" required value="${event ? event.total_tickets : 100}">
            </div>
            ${isPro() ? `
            <div class="form-field">
                <label class="form-label">Пригласительных (лимит, Pro)</label>
                <input class="form-input" type="number" min="0" step="1" id="f_invites" value="${event ? (event.invites_quota || 0) : 0}">
                <div class="hint" style="margin:4px 0 0">Сколько пригласительных можно выдать из непроданных мест</div>
            </div>` : ''}
            ${!event ? `
            <div class="form-field">
                <label class="form-label">Канал (необязательно, если нет — через Mini App)</label>
                <select class="form-input" id="f_channel">
                    <option value="">Без канала (Mini App)</option>
                    ${options}
                </select>
            </div>` : ''}
            <button class="btn btn-primary" type="submit">${eventId ? "💾 Сохранить" : "✅ Создать (черновик)"}</button>
            <button class="btn btn-secondary" type="button" onclick="showAdminEvents()">Отмена</button>
        </form>
    `;
}

function toLocalInputValue(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function submitAdminEventForm(eventId) {
    const title = document.getElementById("f_title").value.trim();
    const description = document.getElementById("f_description").value.trim() || null;
    const dateStr = document.getElementById("f_date").value;
    const location = document.getElementById("f_location").value.trim() || null;
    const price = parseFloat(document.getElementById("f_price").value) || 0;
    const total_tickets = parseInt(document.getElementById("f_tickets").value, 10) || 0;

    if (!title || !dateStr) { showToast("Заполните название и дату", true); return; }
    if (total_tickets <= 0) { showToast("Билетов должно быть > 0", true); return; }

    const invitesQuotaEl = document.getElementById("f_invites");
    const invites_quota = invitesQuotaEl ? (parseInt(invitesQuotaEl.value, 10) || 0) : undefined;

    const payload = {
        title, description,
        date: new Date(dateStr).toISOString(),
        location, price, total_tickets,
    };
    if (invites_quota !== undefined) payload.invites_quota = invites_quota;
    if (!eventId) {
        const channelId = document.getElementById("f_channel").value;
        payload.channel_id = channelId || null;
        if (!channelId && state.me) payload.owner_user_id = state.me.id;
    }

    try {
        if (eventId) {
            await api(`/api/admin/events/${eventId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            showToast("✅ Мероприятие обновлено");
        } else {
            await api("/api/admin/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            showToast("✅ Мероприятие создано (черновик)");
        }
        await showAdminEvents();
    } catch (err) {
        showToast(err.message || "Ошибка сохранения", true);
    }
}

// ─── Мероприятие (детали + статистика + билеты) ─────────────────

async function showAdminEventDetail(eventId) {
    state.lastAction = "showAdminEvents";
    updateToolbar("Мероприятие", true, false);
    showPage("admin-event");
    showLoading();
    try {
        const event = await api(`/api/admin/events/${eventId}`);
        state.currentAdminEvent = event;
        let stats = null, tickets = null, invites = [];
        try { stats = await api(`/api/admin/events/${eventId}/stats`); } catch (e) { /* нет доступа */ }
        try { tickets = await api(`/api/admin/events/${eventId}/tickets`); } catch (e) { /* нет доступа */ }
        try { invites = (await api(`/api/admin/events/${eventId}/invites`)).invites || []; } catch (e) { /* нет доступа */ }
        renderAdminEventDetail(event, stats, tickets ? tickets.tickets : [], invites);
    } catch (err) {
        hideLoading();
        showError(err.message || "Ошибка загрузки");
    }
}

function renderAdminEventDetail(event, stats, tickets, invites) {
    hideLoading();
    const container = document.getElementById("adminEventContent");
    invites = invites || [];

    const statsHtml = stats ? `
        <div class="stat-grid">
            <div class="stat-card"><div class="stat-value">${stats.sold}</div><div class="stat-label">Продано</div></div>
            <div class="stat-card"><div class="stat-value">${stats.available}</div><div class="stat-label">Свободно</div></div>
            <div class="stat-card"><div class="stat-value">${stats.invites_issued != null ? stats.invites_issued + '/' + stats.invites_quota : '—'}</div><div class="stat-label">Пригласит. выдано</div></div>
            <div class="stat-card"><div class="stat-value">${stats.invites_used != null ? stats.invites_used : '—'}</div><div class="stat-label">Пригласит. использовано</div></div>
            <div class="stat-card"><div class="stat-value">${formatPrice(stats.revenue)}</div><div class="stat-label">Выручка</div></div>
        </div>` : '<p class="hint">Статистика недоступна</p>';

    const ticketsHtml = tickets.length === 0
        ? '<p class="hint">Билетов пока нет</p>'
        : `<div class="admin-list">${tickets.map(t => `
            <div class="admin-list-item">
                <div style="flex:1">
                    <div><b>${escapeHtml(t.user_name)}</b> <code>${t.validation_code || '—'}</code>
                        ${t.is_invite ? '<span class="badge badge-tier-pro">приглас.</span>' : ''}</div>
                    <div class="hint">${t.status}${t.checked_in_at ? ' · вход ' + formatDate(t.checked_in_at) : ''} · ${formatDate(t.purchase_date)}</div>
                </div>
                <button class="btn btn-sm btn-secondary" onclick="showTicketQr('${t.id}')">QR</button>
                ${t.status === 'active' && !t.is_invite ? `<button class="btn btn-sm btn-danger" onclick="adminCancelTicket('${t.id}')">Отменить</button>` : ''}
            </div>`).join('')}</div>`;

    // Блок пригласительных
    const invitesHtml = `
        <h3 style="margin:16px 0 8px">Пригласительные ${stats && stats.invites_quota != null ? `(лимит ${stats.invites_quota})` : ''}</h3>
        ${isPro() ? `<button class="btn btn-sm btn-primary" onclick="adminIssueInvitePrompt('${event.id}')">🎟 Выдать пригласительное</button>` : '<p class="hint">Пригласительные доступны на подписке Pro</p>'}
        ${invites.length === 0
            ? '<p class="hint">Пригласительных пока нет</p>'
            : `<div class="admin-list" style="margin-top:10px">${invites.map(iv => `
                <div class="admin-list-item">
                    <div style="flex:1">
                        <div><code>${iv.validation_code || '—'}</code>
                            <span class="badge badge-tier-pro">${iv.seats} чел.</span>
                            ${iv.status === 'checked_in' ? '<span class="badge badge-published">использован</span>' : ''}
                            ${iv.status === 'refunded' ? '<span class="badge badge-off">возвращён</span>' : ''}
                        </div>
                        <div class="hint">${formatDate(iv.purchase_date)}${iv.invited_by ? ' · выдал ' + escapeHtml(iv.invited_by) : ''}</div>
                    </div>
                    <button class="btn btn-sm btn-secondary" onclick="showTicketQr('${iv.id}')">QR</button>
                    ${iv.status === 'active' ? `<button class="btn btn-sm btn-danger" onclick="adminCancelInvite('${event.id}','${iv.id}')">Отменить</button>` : ''}
                </div>`).join('')}</div>`}
    `;

    container.innerHTML = `
        <h2>${escapeHtml(event.title)}</h2>
        <div class="event-meta">
            <div class="meta-row"><span class="meta-label">📅 Дата</span><span>${formatDate(event.date)}</span></div>
            <div class="meta-row"><span class="meta-label">📍 Место</span><span>${escapeHtml(event.location || 'Не указано')}</span></div>
            <div class="meta-row"><span class="meta-label">💰 Цена</span><span>${event.price > 0 ? formatPrice(event.price) : 'Бесплатно'}</span></div>
            <div class="meta-row"><span class="meta-label">🎟 Билетов</span><span>${event.available_tickets}/${event.total_tickets}</span></div>
            <div class="meta-row"><span class="meta-label">Статус</span><span>${event.is_published ? '📢 Опубликовано' : '📝 Черновик'} · ${event.is_active ? '🟢 Активно' : '🔴 Отключено'}</span></div>
        </div>
        ${statsHtml}
        <h3 style="margin:16px 0 8px">Билеты</h3>
        <div style="margin-bottom:12px">
            <a class="btn btn-secondary" href="#" onclick="downloadCsv('${event.id}'); return false;">⬇️ Экспорт CSV</a>
        </div>
        ${ticketsHtml}
        ${invitesHtml}
        <h3 style="margin:16px 0 8px">Действия</h3>
        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <select class="form-input" id="publish_channel_${event.id}" style="width:auto;min-width:180px">
                    <option value="">Без канала (DM)</option>
                    ${(state.me?.channels || []).map(c =>
                        `<option value="${c.id}">${escapeHtml(c.title || c.telegram_channel_id)}</option>`
                    ).join('')}
                </select>
                <button class="btn btn-sm btn-primary" onclick="adminPublish('${event.id}')">📢 Опубликовать</button>
            </div>
            <button class="btn btn-sm btn-secondary" onclick="adminToggle('${event.id}')">${event.is_active ? '⏸ Выключить' : '▶️ Включить'}</button>
            <button class="btn btn-sm btn-secondary" onclick="showAdminEventForm('${event.id}')">✏️ Редактировать</button>
            <button class="btn btn-sm btn-danger" onclick="adminDelete('${event.id}')">🗑 Удалить</button>
        </div>
        <button class="btn btn-secondary" onclick="showAdminEvents()">← К списку</button>
    `;
}

// ─── Пригласительные: выдать / отменить / QR ──────────────────

async function adminIssueInvitePrompt(eventId) {
    const seats = prompt("Вместимость пригласительного (1/2/3 человека):", "1");
    if (!seats) return;
    const n = parseInt(seats, 10);
    if (n < 1 || n > 3) { showToast("Вместимость: 1, 2 или 3", true); return; }
    try {
        const res = await api(`/api/admin/events/${eventId}/invites`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ seats: n }),
        });
        showToast(`✅ Пригласительное выдано: ${res.validation_code}`);
        await showAdminEventDetail(eventId);
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function adminCancelInvite(eventId, ticketId) {
    if (!(await tgConfirm("Отменить пригласительное?"))) return;
    try {
        await api(`/api/admin/events/${eventId}/invites/${ticketId}/cancel`, { method: "POST" });
        showToast("✅ Пригласительное отменено, места возвращены");
        await showAdminEventDetail(eventId);
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function showTicketQr(ticketId) {
    try {
        const resp = await fetch(`/api/admin/tickets/${ticketId}/qr`, { headers: { "X-Init-Data": state.initData } });
        if (!resp.ok) { showToast("Ошибка загрузки QR", true); return; }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const overlay = document.createElement("div");
        overlay.className = "qr-modal";
        overlay.innerHTML = `
            <div class="qr-modal-card">
                <img src="${url}" alt="QR" style="width:220px;height:220px;border-radius:8px">
                <div style="display:flex;gap:8px;margin-top:12px">
                    <button class="btn btn-sm btn-primary" onclick="this.closest('.qr-modal').remove(); downloadQr('${ticketId}')">⬇️ Скачать</button>
                    <button class="btn btn-sm btn-secondary" onclick="this.closest('.qr-modal').remove()">Закрыть</button>
                </div>
            </div>`;
        overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
        document.body.appendChild(overlay);
    } catch (e) { showToast(e.message || "Ошибка QR", true); }
}

async function downloadQr(ticketId) {
    try {
        const resp = await fetch(`/api/admin/tickets/${ticketId}/qr`, { headers: { "X-Init-Data": state.initData } });
        if (!resp.ok) { showToast("Ошибка", true); return; }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `ticket-${ticketId}-qr.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function adminPublish(eventId) {
    const channelSelect = document.getElementById(`publish_channel_${eventId}`);
    const channelId = channelSelect ? channelSelect.value : "";
    try {
        const body = channelId ? JSON.stringify({ channel_id: channelId }) : undefined;
        const res = await api(`/api/admin/events/${eventId}/publish`, {
            method: "POST",
            headers: body ? { "Content-Type": "application/json" } : undefined,
            body,
        });
        const where = channelId ? "" : " в DM";
        showToast(res.announced
            ? `✅ Опубликовано${where}, анонс отправлен`
            : `✅ Опубликовано${where} (анонс не отправлен)`);
    } catch (e) { showToast(e.message || "Ошибка", true); }
    await showAdminEventDetail(eventId);
}

async function adminRepost(eventId) {
    try {
        const res = await api(`/api/admin/events/${eventId}/repost`, { method: "POST" });
        showToast(res.announced ? "✅ Анонс отправлен" : "⚠️ Анонс не отправлен");
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function adminToggle(eventId) {
    try { await api(`/api/admin/events/${eventId}/toggle`, { method: "POST" }); showToast("✅ Статус изменён"); }
    catch (e) { showToast(e.message || "Ошибка", true); }
    await showAdminEventDetail(eventId);
}

async function adminDelete(eventId) {
    if (!(await tgConfirm("Удалить мероприятие?"))) return;
    try { await api(`/api/admin/events/${eventId}/delete`, { method: "POST" }); showToast("✅ Удалено"); await showAdminEvents(); }
    catch (e) { showToast(e.message || "Ошибка", true); }
}

async function adminCancelTicket(ticketId) {
    if (!(await tgConfirm("Отменить билет?"))) return;
    try {
        await api(`/api/admin/tickets/${ticketId}/cancel`, { method: "POST" });
        showToast("✅ Билет отменён");
        if (state.currentAdminEvent) await showAdminEventDetail(state.currentAdminEvent.id);
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function downloadCsv(eventId) {
    try {
        const resp = await fetch(`/api/admin/events/${eventId}/tickets.csv`, { headers: { "X-Init-Data": state.initData } });
        if (!resp.ok) { showToast("Ошибка загрузки CSV", true); return; }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `event-${eventId}-tickets.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (e) { showToast(e.message || "Ошибка CSV", true); }
}

// ─── Проверка билета ───────────────────────────────────────────

function showCheckin() {
    setActiveTab("checkin");
    updateToolbar("Проверка билета", true, false);
    showPage("checkin");
    document.getElementById("checkinContent").innerHTML = `
        <div class="checkin-box">
            <label class="form-label">Код билета</label>
            <input class="form-input" id="ci_code" placeholder="AB3X-K7M9" autocomplete="off" inputmode="text" style="text-transform:uppercase;font-size:20px;letter-spacing:2px;text-align:center">
            <button class="btn btn-primary" onclick="doCheckin()">🔍 Проверить и отметить вход</button>
        </div>
        <div id="checkinResult"></div>
    `;
    const input = document.getElementById("ci_code");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") doCheckin(); });
    setTimeout(() => input.focus(), 100);
}

async function doCheckin() {
    const raw = document.getElementById("ci_code").value.trim().toUpperCase();
    if (!raw) { showToast("Введите код", true); return; }
    // Нормализация: 8 символов без дефиса → XXXX-XXXX
    let code = raw;
    if (code.length === 8 && !code.includes("-")) code = code.slice(0, 4) + "-" + code.slice(4);

    const resultBox = document.getElementById("checkinResult");
    resultBox.innerHTML = '<p class="hint">Проверяю...</p>';

    try {
        // Сначала валидация для информативного ответа
        const info = await api(`/api/admin/tickets/validate?code=${encodeURIComponent(code)}`);
        if (!info.found) {
            resultBox.innerHTML = `<div class="checkin-result checkin-fail">❌ Билет с кодом ${escapeHtml(code)} не найден</div>`;
            return;
        }
        if (info.status === "checked_in") {
            resultBox.innerHTML = `<div class="checkin-result checkin-warn">🟡 Билет уже использован (вход: ${formatDate(info.checked_in_at)})</div>`;
            return;
        }
        if (info.status === "refunded") {
            resultBox.innerHTML = `<div class="checkin-result checkin-fail">❌ Билет возвращён</div>`;
            return;
        }
        // Активный — отмечаем вход
        const res = await api("/api/admin/tickets/checkin", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
        resultBox.innerHTML = `
            <div class="checkin-result checkin-ok">
                ✅ Вход разрешён
                <div class="hint" style="color:inherit">${escapeHtml(info.user_name)} · ${escapeHtml(info.event_title)}</div>
            </div>`;
        document.getElementById("ci_code").value = "";
        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback) {
            window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");
        }
    } catch (err) {
        resultBox.innerHTML = `<div class="checkin-result checkin-fail">❌ ${escapeHtml(err.message || "Ошибка")}</div>`;
    }
}

// ─── Каналы (super-admin) ──────────────────────────────────────

async function showAdminChannels() {
    setActiveTab("channels");
    state.lastAction = "showAdminChannels";
    updateToolbar("Каналы", true, false);
    showPage("admin-channels");
    showLoading();
    try {
        const channels = await api("/api/admin/channels");
        state.adminChannels = channels;
        renderAdminChannels(channels);
    } catch (err) {
        hideLoading();
        showError(err.message || "Ошибка загрузки каналов");
    }
}

function renderAdminChannels(channels) {
    hideLoading();
    const container = document.getElementById("adminChannelsContent");
    if (!channels || channels.length === 0) {
        container.innerHTML = `
            <button class="btn btn-primary" onclick="adminAddChannelPrompt()">➕ Добавить канал</button>
            <div class="empty-state"><div class="empty-icon">📢</div><h3>Нет каналов</h3></div>
        `;
        return;
    }
    container.innerHTML = `
        <button class="btn btn-primary" onclick="adminAddChannelPrompt()">➕ Добавить канал</button>
        <button class="btn btn-secondary" onclick="adminCheckExpired()">🔍 Проверить просроченные подписки</button>
        <div class="admin-list" style="margin-top:12px">
            ${channels.map(ch => `
                <div class="admin-list-item">
                    <div style="flex:1">
                        <div><b>${escapeHtml(ch.title || ch.telegram_channel_id)}</b>
                            <span class="badge ${ch.subscription_tier === 'pro' ? 'badge-tier-pro' : 'badge-tier-basic'}">${ch.subscription_tier}</span>
                            ${ch.is_subscription_active ? '<span class="badge badge-published">активна</span>' : '<span class="badge badge-off">нет подписки</span>'}
                        </div>
                        <div class="hint">${escapeHtml(ch.telegram_channel_id)} · ${ch.admins.length ? 'Админы: ' + ch.admins.map(escapeHtml).join(', ') : '—'}${ch.subscription_until ? ' · до ' + formatDate(ch.subscription_until) : ''}</div>
                    </div>
                    <div style="display:flex;flex-direction:column;gap:6px;min-width:120px">
                        ${ch.is_subscription_active
                            ? `<button class="btn btn-sm btn-secondary" onclick="adminUnsubscribe('${ch.id}')">Отписать</button>`
                            : `<button class="btn btn-sm btn-primary" onclick="adminSubscribePrompt('${ch.id}')">Подписать</button>`}
                        <button class="btn btn-sm btn-secondary" onclick="showAdminChannelSubscription('${ch.id}')">⚙️ Подписка</button>
                        <button class="btn btn-sm btn-secondary" onclick="showChannelInfo('${ch.id}')">ℹ️ Инфо</button>
                        <button class="btn btn-sm btn-secondary" onclick="adminChangeAdminPrompt('${ch.id}')">Сменить админа</button>
                    </div>
                </div>`).join('')}
        </div>
    `;
}

async function adminSubscribePrompt(channelId) {
    const days = prompt("Срок подписки (дней):", "30");
    if (!days) return;
    const tier = prompt("Тариф (basic/pro):", "basic") === "pro" ? "pro" : "basic";
    try {
        await api(`/api/admin/channels/${channelId}/subscribe`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ duration_days: parseInt(days, 10) || 30, tier }),
        });
        showToast("✅ Подписка активирована");
        await showAdminChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function adminUnsubscribe(channelId) {
    if (!(await tgConfirm("Отключить подписку?"))) return;
    try {
        await api(`/api/admin/channels/${channelId}/unsubscribe`, { method: "POST" });
        showToast("✅ Подписка отключена");
        await showAdminChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function adminChangeAdminPrompt(channelId) {
    const newId = prompt("Telegram ID нового админа:");
    if (!newId) return;
    try {
        await api(`/api/admin/channels/${channelId}/change_admin`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_admin_id: newId.trim() }),
        });
        showToast("✅ Админ сменён");
        await showAdminChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

// ─── Мои каналы (самообслуживание для организаторов) ────────────

async function showMyChannels() {
    setActiveTab("admin");
    state.lastAction = "showMyChannels";
    updateToolbar("Мои каналы", false, false);
    showPage("my-channels");
    showLoading();
    try {
        const channels = await api("/api/me/channels");
        state.myChannels = channels;
        renderMyChannels(channels);
    } catch (err) {
        hideLoading();
        showError(err.message || "Ошибка загрузки каналов");
    }
}

function renderMyChannels(channels) {
    hideLoading();
    const container = document.getElementById("myChannelsContent");
    // Форма добавления: <input> вместо prompt() — prompt не работает в Telegram WebView
    let html = `
        <h2 style="margin-bottom:16px">Мои каналы</h2>
        <div class="form-inline" style="margin-bottom:16px;display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
            <div class="form-field" style="flex:1;min-width:150px">
                <label class="form-label">@username или ID канала</label>
                <input class="form-input" id="mc_telegram_id" placeholder="@channel">
            </div>
            <div class="form-field" style="flex:1;min-width:120px">
                <label class="form-label">Название (необязательно)</label>
                <input class="form-input" id="mc_title" placeholder="Мой канал">
            </div>
            <button class="btn btn-primary" onclick="addMyChannel()" style="margin-bottom:0">➕ Добавить</button>
        </div>
    `;
    // Enter key listener
    setTimeout(() => {
        const idInput = document.getElementById("mc_telegram_id");
        if (idInput) {
            idInput.addEventListener("keydown", (e) => { if (e.key === "Enter") addMyChannel(); });
        }
    }, 0);

    if (!channels || channels.length === 0) {
        html += `<div class="empty-state"><div class="empty-icon">📢</div><h3>Нет каналов</h3><p>Добавьте канал по @username — он появится здесь</p></div>`;
    } else {
        html += `<div class="admin-list" style="margin-top:12px">`;
        for (const ch of channels) {
            html += `
                <div class="admin-list-item">
                    <div style="flex:1">
                        <div><b>${escapeHtml(ch.title || ch.telegram_channel_id)}</b></div>
                        <div class="hint">${escapeHtml(ch.telegram_channel_id)}</div>
                    </div>
                </div>`;
        }
        html += `</div>`;
    }
    container.innerHTML = html;
}

async function addMyChannel() {
    const telegramId = document.getElementById("mc_telegram_id").value.trim();
    if (!telegramId) { showToast("Введите @username или ID канала", true); return; }
    const title = document.getElementById("mc_title").value.trim() || null;
    try {
        await api("/api/me/channels", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ telegram_channel_id: telegramId, title }),
        });
        showToast("✅ Канал добавлен");
        // Освежить список каналов и профиль
        await loadMe();
        await showMyChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function adminCheckExpired() {
    try {
        const res = await api("/api/admin/channels/check_expired", { method: "POST" });
        showToast(`✅ Проверено: ${res.checked}, отключено: ${res.deactivated}`);
        await showAdminChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

// ─── Статистика (super-admin) ──────────────────────────────────

async function showAdminStats() {
    setActiveTab("stats");
    state.lastAction = "showAdminStats";
    updateToolbar("Статистика", true, false);
    showPage("admin-stats");
    showLoading();
    try {
        const stats = await api("/api/admin/stats");
        state.globalStats = stats;
        renderAdminStats(stats);
    } catch (err) {
        hideLoading();
        showError(err.message || "Ошибка загрузки статистики");
    }
}

function renderAdminStats(s) {
    hideLoading();
    document.getElementById("adminStatsContent").innerHTML = `
        <div class="stat-grid">
            <div class="stat-card"><div class="stat-value">${s.users_count}</div><div class="stat-label">👥 Пользователей</div></div>
            <div class="stat-card"><div class="stat-value">${s.channels_count}</div><div class="stat-label">📢 Каналов</div></div>
            <div class="stat-card"><div class="stat-value">${s.active_subs}</div><div class="stat-label">Активных подписок</div></div>
            <div class="stat-card"><div class="stat-value">${s.events_count}</div><div class="stat-label">🎫 Мероприятий</div></div>
            <div class="stat-card"><div class="stat-value">${s.upcoming_count}</div><div class="stat-label">Предстоящих</div></div>
            <div class="stat-card"><div class="stat-value">${s.tickets_active}</div><div class="stat-label">🎟 Активных билетов</div></div>
            <div class="stat-card stat-revenue"><div class="stat-value">${formatPrice(s.revenue)}</div><div class="stat-label">💰 Выручка</div></div>
        </div>
    `;
}

// ─── Добавить канал (super-admin) ─────────────────────────────

async function adminAddChannelPrompt() {
    const telegramChannelId = prompt("Telegram ID канала (@username или числовой):");
    if (!telegramChannelId) return;
    const days = prompt("Срок подписки (дней):", "30");
    if (!days) return;
    const tier = prompt("Тариф (basic/pro):", "basic") === "pro" ? "pro" : "basic";
    const title = prompt("Название (необязательно):", "") || null;
    try {
        await api("/api/admin/channels", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                telegram_channel_id: telegramChannelId.trim(),
                title,
                duration_days: parseInt(days, 10) || 30,
                tier,
            }),
        });
        showToast("✅ Канал добавлен и подписка активирована");
        await showAdminChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

// ─── Рассылка (super-admin) ───────────────────────────────────

function showBroadcast() {
    updateToolbar("Рассылка", true, false);
    showPage("admin-broadcast");
    document.getElementById("adminBroadcastContent").innerHTML = `
        <div class="form-field">
            <label class="form-label">Сообщение для всех активных каналов</label>
            <textarea class="form-input" id="bc_text" placeholder="Введите текст рассылки..." style="min-height:120px"></textarea>
        </div>
        <button class="btn btn-primary" onclick="doBroadcast()">📣 Отправить</button>
        <div id="bcResult"></div>
    `;
}

async function doBroadcast() {
    const text = document.getElementById("bc_text").value.trim();
    if (!text) { showToast("Введите текст", true); return; }
    const btn = document.querySelector('#adminBroadcastContent .btn-primary');
    btn.disabled = true;
    try {
        const res = await api("/api/admin/broadcast", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
        });
        document.getElementById("bcResult").innerHTML =
            `<div class="checkin-result checkin-ok">✅ Отправлено в ${res.sent}/${res.total} каналов</div>`;
        document.getElementById("bc_text").value = "";
    } catch (e) {
        showToast(e.message || "Ошибка", true);
    } finally {
        btn.disabled = false;
    }
}

// ─── Инфо о пользователе (super-admin) ───────────────────────

function showUserInfo() {
    updateToolbar("Инфо о пользователе", true, false);
    showPage("admin-userinfo");
    document.getElementById("adminUserInfoContent").innerHTML = `
        <div class="form-field">
            <label class="form-label">Telegram ID пользователя</label>
            <input class="form-input" id="ui_userid" placeholder="123456789" inputmode="numeric">
        </div>
        <button class="btn btn-primary" onclick="doUserInfoLookup()">🔍 Найти</button>
        <div id="uiResult"></div>
    `;
    const input = document.getElementById("ui_userid");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") doUserInfoLookup(); });
}

async function doUserInfoLookup() {
    const id = document.getElementById("ui_userid").value.trim();
    if (!id) { showToast("Введите Telegram ID", true); return; }
    const resultBox = document.getElementById("uiResult");
    resultBox.innerHTML = '<p class="hint">Поиск...</p>';
    try {
        const user = await api(`/api/admin/users/${encodeURIComponent(id)}`);
        const channels = user.channels || [];
        resultBox.innerHTML = `
            <div class="profile-card" style="margin-top:16px">
                <div class="profile-avatar">👤</div>
                <h2>${escapeHtml(user.name || "Без имени")}</h2>
                <p class="hint">Telegram ID: <code>${escapeHtml(user.telegram_user_id)}</code></p>
            </div>
            <h3 style="margin:16px 0 8px">Каналы (${channels.length})</h3>
            ${channels.length === 0
                ? '<p class="hint">Нет каналов</p>'
                : `<div class="admin-list">${channels.map(ch => `
                    <div class="admin-list-item">
                        <div><b>${escapeHtml(ch.title || ch.telegram_channel_id)}</b>
                            <span class="badge ${ch.subscription_tier === 'pro' ? 'badge-tier-pro' : 'badge-tier-basic'}">${ch.subscription_tier}</span>
                            ${ch.is_subscription_active ? '<span class="badge badge-published">активна</span>' : '<span class="badge badge-off">нет</span>'}
                        </div>
                    </div>`).join('')}</div>`}
        `;
    } catch (e) {
        resultBox.innerHTML = `<div class="checkin-result checkin-fail">❌ ${escapeHtml(e.message || "Пользователь не найден")}</div>`;
    }
}

// ─── Здоровье (super-admin) ───────────────────────────────────

async function showAdminHealth() {
    updateToolbar("Здоровье", true, false);
    showPage("admin-health");
    showLoading();
    try {
        const h = await api("/api/admin/health");
        hideLoading();
        document.getElementById("adminHealthContent").innerHTML = `
            <div class="stat-grid">
                <div class="stat-card ${h.status === 'ok' ? 'checkin-ok' : 'checkin-fail'}">
                    <div class="stat-value">${h.status === 'ok' ? '✅' : '⚠️'}</div>
                    <div class="stat-label">Статус</div>
                </div>
                <div class="stat-card"><div class="stat-value">${h.db_ok ? '✅' : '❌'}</div><div class="stat-label">База данных</div></div>
            </div>
            <div class="admin-list-item" style="margin-top:12px">
                <div><b>🤖 Бот</b></div>
                <div class="hint">${h.bot_username ? '@' + escapeHtml(h.bot_username) : 'неизвестно'}</div>
            </div>
        `;
    } catch (e) {
        hideLoading();
        showError(e.message || "Ошибка загрузки");
    }
}

// ═══════════════════════════════════════════════════════════════
// Управление подпиской канала (super-admin): тип + срок
// ═══════════════════════════════════════════════════════════════

function showAdminChannelSubscription(channelId) {
    const channel = (state.adminChannels || []).find(c => c.id === channelId);
    if (!channel) { showToast("Канал не найден", true); return; }

    updateToolbar("Подписка канала", true, false);
    showPage("admin-channel-subscription");

    const curTier = channel.subscription_tier === "pro" ? "pro" : "basic";
    document.getElementById("adminChannelSubContent").innerHTML = `
        <h2 style="margin-bottom:8px">${escapeHtml(channel.title || channel.telegram_channel_id)}</h2>
        <p class="hint">${escapeHtml(channel.telegram_channel_id)}${channel.subscription_until ? ' · до ' + formatDate(channel.subscription_until) : ''}</p>

        <div class="form-field">
            <label class="form-label">Тип подписки (тариф)</label>
            <select class="form-input" id="sub_tier">
                <option value="basic" ${curTier === 'basic' ? 'selected' : ''}>Basic</option>
                <option value="pro" ${curTier === 'pro' ? 'selected' : ''}>Pro</option>
            </select>
        </div>
        <div class="form-field">
            <label class="form-label">Период</label>
            <div style="display:flex;gap:8px">
                <input class="form-input" type="number" min="1" step="1" id="sub_period" value="1" style="flex:1">
                <select class="form-input" id="sub_unit" style="flex:1">
                    <option value="days">Дней</option>
                    <option value="months" selected>Месяцев</option>
                    <option value="years">Лет</option>
                </select>
            </div>
        </div>
        <button class="btn btn-primary" onclick="applySubscription('${channelId}')">💾 Применить (тип + срок)</button>
        <button class="btn btn-secondary" onclick="changeTier('${channelId}')">🔄 Только сменить тариф</button>
        <button class="btn btn-secondary" onclick="showAdminChannels()">← К списку</button>
    `;
}

async function applySubscription(channelId) {
    const tier = document.getElementById("sub_tier").value;
    const period = parseInt(document.getElementById("sub_period").value, 10);
    const period_unit = document.getElementById("sub_unit").value;
    if (!period || period <= 0) { showToast("Укажите количество", true); return; }
    try {
        await api(`/api/admin/channels/${channelId}/subscription`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tier, period, period_unit }),
        });
        showToast("✅ Подписка обновлена");
        await showAdminChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

async function changeTier(channelId) {
    // Используем выбранный в форме тариф (не prompt — он дублирует select и не работает в Telegram)
    const tier = document.getElementById("sub_tier").value;
    if (tier !== "basic" && tier !== "pro") { showToast("Тариф: basic или pro", true); return; }
    try {
        await api(`/api/admin/channels/${channelId}/tier`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tier }),
        });
        showToast("✅ Тариф сменён");
        await showAdminChannels();
    } catch (e) { showToast(e.message || "Ошибка", true); }
}

// ═══════════════════════════════════════════════════════════════
// Инфо о канале (детальная сводка, super-admin)
// ═══════════════════════════════════════════════════════════════

async function showChannelInfo(channelId) {
    updateToolbar("Инфо о канале", true, false);
    showPage("admin-channels");
    const container = document.getElementById("adminChannelsContent");
    showLoading();
    try {
        const info = await api(`/api/admin/channels/${channelId}`);
        hideLoading();
        container.innerHTML = `
            <h2 style="margin-bottom:8px">${escapeHtml(info.title || info.telegram_channel_id)}</h2>
            <p class="hint">${escapeHtml(info.telegram_channel_id)}</p>
            <div class="event-meta">
                <div class="meta-row"><span class="meta-label">Статус</span><span>${info.is_subscription_active ? '🟢 Активна' : '🔴 Неактивна'}</span></div>
                <div class="meta-row"><span class="meta-label">Тариф</span><span>${info.subscription_tier}</span></div>
                <div class="meta-row"><span class="meta-label">Подписка до</span><span>${info.subscription_until ? formatDate(info.subscription_until) : '—'}</span></div>
                <div class="meta-row"><span class="meta-label">Админы</span><span>${(info.admins || []).length ? info.admins.map(escapeHtml).join(', ') : '—'}</span></div>
                <div class="meta-row"><span class="meta-label">Мероприятий</span><span>${info.events_count}</span></div>
                <div class="meta-row"><span class="meta-label">Предстоящих</span><span>${info.upcoming_count}</span></div>
                <div class="meta-row"><span class="meta-label">Продано билетов</span><span>${info.tickets_sold}</span></div>
            </div>
            <button class="btn btn-secondary" onclick="showAdminChannels()">← К списку каналов</button>
        `;
    } catch (e) {
        hideLoading();
        showError(e.message || "Ошибка загрузки канала");
    }
}
