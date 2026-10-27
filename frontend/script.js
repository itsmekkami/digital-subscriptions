const API = "";
const tokenKey = "digitalContentToken";
let accessToken = localStorage.getItem(tokenKey);

const catalog = document.getElementById("catalog");
const catalogStatus = document.getElementById("catalog-status");
const authStatus = document.getElementById("auth-status");
const purchaseStatus = document.getElementById("purchase-status");
const userInfo = document.getElementById("user-info");
const adminSection = document.getElementById("admin-section");
const adminStatus = document.getElementById("admin-status");
const adminSubscriptions = document.getElementById("admin-subscriptions");
const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const statusLabels = {
    active: "Активна",
    expired: "Истекла",
    cancelled: "Отменена",
};

const statusClasses = {
    active: "status-active",
    expired: "status-expired",
    cancelled: "status-cancelled",
};

function setMessage(element, message, isError = false) {
    element.textContent = message;
    element.classList.toggle("error", isError);
}

function showPurchaseMessage(message, isError = false) {
    purchaseStatus.textContent = message;
    purchaseStatus.classList.remove("hidden");
    purchaseStatus.classList.toggle("error", isError);
}

async function request(path, options = {}) {
    const headers = {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(accessToken
            ? { Authorization: `Bearer ${accessToken}` }
            : {}),
        ...options.headers,
    };

    const response = await fetch(`${API}${path}`, {
        ...options,
        headers,
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        const detail = typeof data.detail === "string"
            ? data.detail
            : Array.isArray(data.detail)
                ? data.detail.map(item => item.msg).join("; ")
                : data.detail?.message || "Не удалось выполнить запрос";

        throw new Error(detail);
    }

    return data;
}

function updateAccountInterface() {
    const loggedIn = Boolean(accessToken);

    userInfo.textContent = loggedIn
        ? "Вы вошли в аккаунт"
        : "Вы не вошли в аккаунт";

    document.getElementById("logout-button")
        .classList.toggle("hidden", !loggedIn);

    document.getElementById("auth-section")
        .classList.toggle("hidden", loggedIn);

    document.getElementById("subscriptions-section")
        .classList.toggle("hidden", !loggedIn);
}

document.getElementById("show-login").addEventListener("click", () => {
    loginForm.classList.remove("hidden");
    registerForm.classList.add("hidden");
    setMessage(authStatus, "");
});

document.getElementById("show-register").addEventListener("click", () => {
    registerForm.classList.remove("hidden");
    loginForm.classList.add("hidden");
    setMessage(authStatus, "");
});

registerForm.addEventListener("submit", async event => {
    event.preventDefault();

    const button = registerForm.querySelector('button[type="submit"]');
    button.disabled = true;

    try {
        const data = await request("/api/register", {
            method: "POST",
            body: JSON.stringify({
                name: document.getElementById("register-name").value.trim(),
                email: document.getElementById("register-email").value.trim(),
                password: document.getElementById("register-password").value,
            }),
        });

        registerForm.reset();
        loginForm.classList.remove("hidden");
        registerForm.classList.add("hidden");

        document.getElementById("login-email").value = data.user.email;

        setMessage(authStatus, "Регистрация успешна. Теперь войдите в аккаунт");
    } catch (error) {
        setMessage(authStatus, error.message, true);
    } finally {
        button.disabled = false;
    }
});

loginForm.addEventListener("submit", async event => {
    event.preventDefault();

    const button = loginForm.querySelector('button[type="submit"]');
    button.disabled = true;

    try {
        const data = await request("/api/login", {
            method: "POST",
            body: JSON.stringify({
                email: document.getElementById("login-email").value.trim(),
                password: document.getElementById("login-password").value,
            }),
        });

        accessToken = data.access_token;
        localStorage.setItem(tokenKey, accessToken);

        loginForm.reset();
        setMessage(authStatus, "Вход выполнен успешно");

        updateAccountInterface();
        await loadCurrentUser();
        await loadMySubscriptions();
    } catch (error) {
        setMessage(authStatus, error.message, true);
    } finally {
        button.disabled = false;
    }
});

document.getElementById("logout-button").addEventListener("click", () => {
    accessToken = null;
    localStorage.removeItem(tokenKey);

    updateAccountInterface();

    document.getElementById("my-subscriptions").replaceChildren();
    document.getElementById("subscriptions-status").textContent = "";

    adminSection.classList.add("hidden");
    adminSubscriptions.replaceChildren();
    adminStatus.textContent = "";

    userInfo.textContent = "Вы не вошли в аккаунт";

    setMessage(authStatus, "Вы вышли из аккаунта");
    setMessage(purchaseStatus, "");
    purchaseStatus.classList.add("hidden");
});

async function loadCurrentUser() {
    try {
        const user = await request("/api/me");
        userInfo.textContent = `${user.name} (${user.email})`;
        adminSection.classList.toggle(
            "hidden",
            user.role !== "admin"
        );

        if (user.role === "admin") {
            await loadAdminSubscriptions();
        }

    } catch (error) {
        accessToken = null;
        localStorage.removeItem(tokenKey);
        adminSection.classList.add("hidden");
        adminSubscriptions.replaceChildren();
        updateAccountInterface();
        setMessage(authStatus, "Сессия завершилась. Войдите снова", true);
    }
}

async function loadCatalog() {
    try {
        const items = await request("/api/catalog");

        catalog.replaceChildren();

        if (items.length === 0) {
            catalogStatus.textContent = "Пока нет доступных подписок";
            return;
        }

        for (const item of items) {
            const card = document.createElement("article");
            card.className = "plan-card";

            const title = document.createElement("h3");
            title.textContent = item.title;

            const description = document.createElement("p");
            description.textContent = item.description;

            const price = document.createElement("div");
            price.className = "price";
            price.textContent = `${item.price} ${item.currency}`;

            const button = document.createElement("button");
            button.type = "button";
            button.className = "button";
            button.textContent = "Купить подписку";
            button.addEventListener("click", () => purchasePlan(item.id, button));

            card.append(title, description, price, button);
            catalog.appendChild(card);
        }

        catalogStatus.textContent = "Выберите подходящий тариф";
    } catch (error) {
        catalogStatus.textContent = `Ошибка загрузки каталога: ${error.message}`;
    }
}

async function purchasePlan(planId, button) {
    if (!accessToken) {
        showPurchaseMessage(
            "Сначала войдите в аккаунт, чтобы купить подписку",
            true
        );
        document.getElementById("auth-section").scrollIntoView({
            behavior: "smooth",
        });
        return;
    }

    const paymentChoice = window.confirm(
        "Тестовая оплата:\n\n" +
        "Да - успешная оплата\n" +
        "Нет - неуспешная оплата"
    );

    button.disabled = true;
    showPurchaseMessage("Обрабатываем тестовый платёж...");

    try {
        const result = await request("/api/purchase", {
            method: "POST",
            body: JSON.stringify({
                plan_id: planId,
                simulate_success: paymentChoice,
            }),
        });

        showPurchaseMessage(
            result.message || "Подписка успешно оформлена"
        );
        await loadMySubscriptions();
    } catch (error) {
        showPurchaseMessage(error.message, true);
    } finally {
        button.disabled = false;
    }
}

async function loadMySubscriptions() {
    const container = document.getElementById("my-subscriptions");
    const status = document.getElementById("subscriptions-status");

    if (!accessToken) {
        return;
    }

    try {
        const items = await request("/api/my-subscriptions");

        container.replaceChildren();

        if (items.length === 0) {
            status.textContent = "У вас пока нет оформленных подписок";
            return;
        }

        status.textContent = "";

        for (const item of items) {
            const card = document.createElement("div");
            card.className = "plan-card";

            const title = document.createElement("h3");
            title.textContent = item.plan_name;

            const dates = document.createElement("p");
            dates.textContent =
                `С ${item.start_date} по ${item.end_date}`;

            const state = document.createElement("p");
            const statusText =
                statusLabels[item.status] ?? item.status;

            state.textContent = `Статус: ${statusText}`;
            
            card.append(title, dates, state);

            if (item.status === "active") {
                const cancelButton = document.createElement("button");
                cancelButton.type = "button";
                cancelButton.className = "button-cancel";
                cancelButton.textContent = "Отменить подписку";

                cancelButton.addEventListener("click", async () => {
                    const confirmed = window.confirm(
                        "Вы действительно хотите отменить подписку?"
                    );

                    if (!confirmed) {
                        return;
                    }

                    cancelButton.disabled = true;

                    try {
                        const result = await request(
                            `/api/my-subscriptions/${item.id}/cancel`,
                            { method: "POST" }
                        );

                        showPurchaseMessage(result.message);
                        await loadMySubscriptions();
                    } catch (error) {
                        showPurchaseMessage(error.message, true);
                    } finally {
                        cancelButton.disabled = false;
                    }
                });

                card.appendChild(cancelButton);
            }
            container.appendChild(card);
        }
    } catch (error) {
        status.textContent =
            "Не удалось загрузить подписки. Попробуйте обновить страницу";
        console.error("Ошибка загрузки подписок:", error);
    }
}

async function loadAdminSubscriptions() {
    const status = document.getElementById("admin-status");
    const tableBody = document.getElementById("admin-subscriptions");

    status.textContent = "Загрузка подписок...";
    tableBody.innerHTML = "";

    try {
        const subscriptions = await request("/api/admin/subscriptions");

        if (subscriptions.length === 0) {
            status.textContent = "Подписок пока нет";
            return;
        }

        for (const subscription of subscriptions) {
            const row = document.createElement("tr");

            const values = [
                subscription.id,
                subscription.user_name,
                subscription.user_email,
                subscription.plan_name,
                subscription.start_date,
                subscription.end_date,
                statusLabels[subscription.status] ?? subscription.status,
            ];
                        
            for (let i = 0; i < values.length; i++) {
                const cell = document.createElement("td");

                if (i === values.length - 1) {
                    const badge = document.createElement("span");

                    badge.classList.add("subscription-status");
                    badge.textContent =
                        statusLabels[subscription.status] ?? subscription.status;

                    const statusClass = statusClasses[subscription.status];

                    if (statusClass) {
                        badge.classList.add(statusClass);
                    }

                    cell.appendChild(badge);
                } else {
                    cell.textContent = values[i] ?? "—";
                }

                row.appendChild(cell);
            }

            tableBody.appendChild(row);
        }

        status.textContent = `Всего подписок: ${subscriptions.length}`;
    } catch (error) {
        status.textContent = error.message;
    }
}

document.getElementById("refresh-admin-button")
    .addEventListener("click", loadAdminSubscriptions);

async function initialize() {
    updateAccountInterface();
    await loadCatalog();

    if (accessToken) {
        await loadCurrentUser();

        if (accessToken) {
            await loadMySubscriptions();
        }
    }
}

initialize();