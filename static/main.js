let currentProducts = [];
let cart = JSON.parse(localStorage.getItem('cart')) || [];

// Переменные для поиска и пагинации
let currentCategory = '';
let currentVendor = '';
let currentSearch = '';
let currentPage = 1;
let searchTimeout = null;

// --- КНОПКА ВВЕРХ ---
window.addEventListener('scroll', () => {
    const btn = document.getElementById('scrollToTopBtn');
    if (btn) {
        if (window.scrollY > 300) {
            btn.classList.add('show');
        } else {
            btn.classList.remove('show');
        }
    }
});

function scrollToTop() {
    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}
document.addEventListener("DOMContentLoaded", () => {
    checkAuthStatus();
    updateCartCount();
    renderHomePage();
});

// --- СИСТЕМА УВЕДОМЛЕНИЙ ---
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.style.borderLeftColor = type === 'error' ? '#d32f2f' : 'var(--accent-crimson)';
    
    const span = document.createElement('span');
    span.textContent = message;
    toast.appendChild(span);
    
    container.appendChild(toast);
    setTimeout(() => { 
        toast.classList.add('fade-out'); 
        setTimeout(() => toast.remove(), 300); 
    }, 3000);
}

function customConfirm(message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal-content" style="max-width: 400px; text-align: center; padding: 2rem;">
            <h3 style="margin-top:0; color: var(--text-main);">Подтверждение</h3>
            <p style="color: var(--text-graphite); margin: 1.5rem 0 2rem 0; font-size: 1.1rem;">${escapeHTML(message)}</p>
            <div style="display: flex; justify-content: center; gap: 1rem;">
                <button id="btn-cancel" class="btn-primary" style="background: #ccc; color: #333;">Отмена</button>
                <button id="btn-ok" class="btn-primary" style="background: var(--accent-crimson);">Подтвердить</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    document.getElementById('btn-cancel').onclick = () => overlay.remove();
    document.getElementById('btn-ok').onclick = () => { overlay.remove(); onConfirm(); };
}

// --- БЕЗОПАСНОСТЬ (XSS И JWT) ---
function escapeHTML(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, function(m) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
    });
}

async function fetchAuth(url, options = {}) {
    const token = localStorage.getItem('access_token');
    if (!options.headers) options.headers = {};
    if (token) options.headers['Authorization'] = `Bearer ${token}`;
    
    try {
        const res = await fetch(url, options);
        if (res.status === 401) {
            localStorage.clear();
            showToast("Сессия истекла. Войдите заново.", "error");
            setTimeout(() => window.location.reload(), 1500);
            throw new Error("Unauthorized");
        }
        return res;
    } catch (e) { throw e; }
}

// --- НАВИГАЦИЯ ---
function renderHomePage() {
    const template = document.getElementById('home-page-template');
    document.getElementById('app-content').innerHTML = template.innerHTML;
}

// --- АВТОРИЗАЦИЯ И ПРОФИЛЬ ---
function checkAuthStatus() {
    const token = localStorage.getItem('access_token');
    const role = localStorage.getItem('user_role');
    const username = localStorage.getItem('username');
    
    document.getElementById('login-link').style.display = token ? 'none' : 'inline';
    document.getElementById('user-menu').style.display = token ? 'inline-block' : 'none';
    document.getElementById('admin-link').style.display = (token && role === 'admin') ? 'inline' : 'none';
    
    if (token && username) {
        document.getElementById('username-display').textContent = username + ' ▼';
    }
}

function showAuthModal() { document.getElementById('auth-modal').style.display = 'flex'; }
function closeAuthModal() { document.getElementById('auth-modal').style.display = 'none'; }

function switchAuthTab(tab, element) {
    document.getElementById('login-form').style.display = tab === 'login' ? 'block' : 'none';
    document.getElementById('register-form').style.display = tab === 'register' ? 'block' : 'none';
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    if (element) element.classList.add('active');
}

function logout() {
    localStorage.clear();
    checkAuthStatus();
    showToast("Вы успешно вышли из системы");
    renderHomePage();
}

async function submitLogin(event) {
    event.preventDefault();
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;
    try {
        const res = await fetch('/api/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok) {
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('user_role', data.role);
            localStorage.setItem('username', data.username);
            closeAuthModal();
            checkAuthStatus();
            showToast("Вход выполнен успешно!");
        } else {
            showToast(data.detail || "Ошибка входа", "error");
        }
    } catch (e) { showToast("Ошибка сети", "error"); }
}

async function submitRegister(event) {
    event.preventDefault();
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;

    // Клиентская проверка пароля (сервер тоже проверяет)
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
        showToast("Пароль должен быть минимум 8 символов, содержать буквы и цифры", "error");
        return;
    }

    try {
        const res = await fetch('/api/register', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Успешно! Никнейм: ${data.username}. Выполните вход.`);
            switchAuthTab('login', document.querySelectorAll('.auth-tab')[0]);
        } else {
            showToast(data.detail || "Ошибка регистрации", "error");
        }
    } catch (e) { showToast("Ошибка сети", "error"); }
}

async function loadProfile() {
    const content = document.getElementById('app-content');
    content.innerHTML = '<div style="text-align:center; padding:3rem;">Загрузка профиля...</div>';

    try {
        const userRes = await fetchAuth(`/api/profile`);
        if (!userRes.ok) return; 
        const userData = await userRes.json();
        
        const ordersRes = await fetchAuth(`/api/orders/user`);
        const orders = await ordersRes.json();

        let ordersHtml = orders.length === 0 ? '<p>У вас пока нет заказов.</p>' : '';
        orders.forEach(o => {
            const color = o.status === 'Отменен' ? 'red' : (o.status === 'В обработке' ? 'orange' : 'green');
            const cancelBtn = o.status === 'В обработке' 
                ? `<button class="btn-danger btn-sm" onclick="userCancelOrder(${o.id})">Отменить заказ</button>` : '';
            ordersHtml += `
                <div style="border:1px solid #ddd; border-radius:6px; padding:1rem; margin-bottom:1rem; background:#fafafa;">
                    <div style="display:flex; justify-content:space-between; border-bottom:1px solid #ddd; padding-bottom:0.5rem; margin-bottom:0.5rem;">
                        <strong>Заказ #${o.id}</strong><span style="color:${color}; font-weight:bold;">${escapeHTML(o.status)}</span>
                    </div>
                    <p style="margin:0.5rem 0;">Сумма: <strong>$${o.total_price}</strong> | Дата: ${new Date(o.created_at).toLocaleString()}</p>
                    <div style="text-align:right;">${cancelBtn}</div>
                </div>`;
        });

        content.innerHTML = `
            <div style="max-width:1000px; margin:2rem auto; display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:2rem; padding: 0 1rem;">
                <div style="background:white; padding:2rem; border-radius:8px; box-shadow:var(--shadow-sm);">
                    <h2 style="margin-bottom:1.5rem; color:var(--accent-crimson);">Личные данные</h2>
                    <form onsubmit="updateProfile(event)">
                        <div class="form-group"><label>Email</label><input type="text" value="${escapeHTML(userData.email)}" readonly style="background:#f0f0f0;"></div>
                        <div class="form-group"><label>Никнейм</label><input type="text" id="prof-user" value="${escapeHTML(userData.username)}" required></div>
                        <div class="form-group"><label>Телефон</label><input type="tel" id="prof-phone" value="${escapeHTML(userData.phone || '')}"></div>
                        <div class="form-group"><label>Адрес</label><textarea id="prof-addr" rows="2">${escapeHTML(userData.address || '')}</textarea></div>
                        <div class="form-group"><label>Новый пароль</label><input type="password" id="prof-pass" placeholder="Оставьте пустым, если не меняете"></div>
                        <button type="submit" class="btn-primary" style="width:100%;">Сохранить</button>
                    </form>
                </div>
                <div style="background:white; padding:2rem; border-radius:8px; box-shadow:var(--shadow-sm);">
                    <h2 style="margin-bottom:1.5rem; color:var(--accent-crimson);">Мои заказы</h2>
                    ${ordersHtml}
                </div>
            </div>`;
    } catch (e) { showToast("Ошибка загрузки", "error"); }
}

async function updateProfile(e) {
    e.preventDefault();
    const payload = {
        username: document.getElementById('prof-user').value,
        phone: document.getElementById('prof-phone').value,
        address: document.getElementById('prof-addr').value,
        password: document.getElementById('prof-pass').value || null
    };
    try {
        const res = await fetchAuth('/api/profile', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
        if (res.ok) {
            localStorage.setItem('username', payload.username);
            checkAuthStatus();
            showToast('Профиль обновлен');
            loadProfile();
        } else {
            const err = await res.json();
            showToast(err.detail || "Ошибка сохранения", "error");
        }
    } catch (e) { showToast("Ошибка сети", "error"); }
}

async function userCancelOrder(id) {
    customConfirm(`Вы уверены, что хотите отменить заказ #${id}?`, async () => {
        const res = await fetchAuth(`/api/orders/${id}/cancel`, { method: 'PUT' });
        if (res.ok) { showToast('Заказ отменен'); loadProfile(); }
        else { const err = await res.json(); showToast(err.detail || 'Ошибка отмены', 'error'); }
    });
}

// --- КАТАЛОГ И ТОВАРЫ ---
function catActive(slug, current) { return slug === current ? 'active-filter' : ''; }
function venActive(name, current) { return name === current ? 'active-filter' : ''; }

async function loadCatalog(category = '', vendor = '', search = '', page = 1) {
    // Сохраняем состояние для поиска и пагинации
    currentCategory = category;
    currentVendor = vendor;
    currentSearch = search;
    currentPage = page;

    const content = document.getElementById('app-content');
    const isAdmin = localStorage.getItem('user_role') === 'admin';
    
    // Показываем скелетоны при загрузке (если это не первая загрузка с фильтрами)
    if (!document.querySelector('.catalog-layout')) {
        const skeletonTemplate = document.getElementById('skeleton-template');
        content.innerHTML = `<div class="catalog-layout"><aside class="sidebar"></aside><section class="catalog-content"><div id="skeleton-container">${skeletonTemplate.innerHTML}</div></section></div>`;
    } else {
        // Если мы уже в каталоге, просто показываем скелетоны вместо сетки
        const grid = document.querySelector('.catalog-grid');
        if (grid) {
            const skeletonTemplate = document.getElementById('skeleton-template');
            grid.innerHTML = skeletonTemplate.innerHTML;
        }
    }
    
    try {
        let url = `/api/products?page=${page}&limit=12`;
        if (category) url += `&category_slug=${category}`;
        if (vendor) url += `&vendor=${vendor}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        
        const res = await fetch(url);
        const data = await res.json();
        currentProducts = data.items;
        
        const catNames = { '': 'Все оборудование', 'switches': 'Коммутаторы', 'transceivers': 'Трансиверы', 'cables': 'Кабели' };
        const pageTitle = (catNames[category] || 'Каталог') + (vendor ? ` — ${vendor}` : '');
        
        let html = `<div class="catalog-layout"><aside class="sidebar">
            <h3 style="color:var(--accent-crimson); border-bottom:1px solid #ddd; padding-bottom:10px;">Категории</h3>
            <ul style="list-style:none; padding:0; line-height:2;">
                <li><a href="#" class="${catActive('', category)}" onclick="loadCatalog('','${vendor}', currentSearch, 1); return false;">Все оборудование</a></li>
                <li><a href="#" class="${catActive('switches', category)}" onclick="loadCatalog('switches','${vendor}', currentSearch, 1); return false;">Коммутаторы</a></li>
                <li><a href="#" class="${catActive('transceivers', category)}" onclick="loadCatalog('transceivers','${vendor}', currentSearch, 1); return false;">Трансиверы</a></li>
                <li><a href="#" class="${catActive('cables', category)}" onclick="loadCatalog('cables','${vendor}', currentSearch, 1); return false;">Кабели</a></li>
            </ul>
            <h3 style="color:var(--accent-crimson); border-bottom:1px solid #ddd; padding-bottom:10px; margin-top:1.5rem;">Вендоры</h3>
            <ul style="list-style:none; padding:0; line-height:2;">
                <li><a href="#" class="${venActive('', vendor)}" onclick="loadCatalog('${category}','', currentSearch, 1); return false;">Все</a></li>
                <li><a href="#" class="${venActive('Cisco', vendor)}" onclick="loadCatalog('${category}','Cisco', currentSearch, 1); return false;">Cisco</a></li>
                <li><a href="#" class="${venActive('Arista', vendor)}" onclick="loadCatalog('${category}','Arista', currentSearch, 1); return false;">Arista</a></li>
                <li><a href="#" class="${venActive('Huawei', vendor)}" onclick="loadCatalog('${category}','Huawei', currentSearch, 1); return false;">Huawei</a></li>
                <li><a href="#" class="${venActive('Juniper', vendor)}" onclick="loadCatalog('${category}','Juniper', currentSearch, 1); return false;">Juniper</a></li>
            </ul>
        </aside><section class="catalog-content">
            <div class="catalog-header">
                <h2 style="margin: 0; color: var(--text-main);">${pageTitle}</h2>
                <div class="search-box">
                    <input type="text" id="search-input" placeholder="Поиск по модели или Part Number..." value="${escapeHTML(search)}" oninput="handleSearch(this.value)">
                </div>
            </div>
            <div class="catalog-grid">`;
        
        if (isAdmin) {
            let cId = category === 'switches' ? '1' : (category === 'transceivers' ? '2' : (category === 'cables' ? '3' : '1'));
            html += `<div class="product-card" style="border: 2px dashed var(--accent-crimson); justify-content: center; align-items:center; cursor: pointer; background: var(--surface-light);" onclick="openAdminModal(null, '${vendor||'Cisco'}', '${cId}')">
                <div style="font-size:3rem; color:var(--accent-crimson); font-weight:bold;">+</div><h3>Добавить товар</h3>
            </div>`;
        }

        if (currentProducts.length === 0 && !isAdmin) {
            html += `<p style="grid-column: 1/-1; text-align: center; color: #777;">По вашему запросу ничего не найдено.</p>`;
        }

        currentProducts.forEach(p => {
            const imgSrc = p.image_url ? escapeHTML(p.image_url) : '';
            const img = imgSrc 
                ? `<img src="${imgSrc}" class="card-image-placeholder" style="cursor:pointer" onclick="showProductPage(${p.id})">` 
                : `<div class="card-image-placeholder" style="cursor:pointer" onclick="showProductPage(${p.id})">Нет фото</div>`;
            
            const cItem = cart.find(i => i.id === p.id);
            const qty = cItem ? cItem.quantity : 0;
            const safeModel = escapeHTML(p.model_name).replace(/'/g, "\\'");
            
            const btn = qty === 0 
                ? `<button class="btn-primary btn-sm" onclick="changeQuantity(${p.id}, '${safeModel}', ${p.price}, 1)">В корзину</button>`
                : `<div><button class="btn-primary btn-sm" onclick="changeQuantity(${p.id}, '${safeModel}', ${p.price}, -1)">-</button> <span style="font-weight:bold; margin:0 5px;">${qty}</span> <button class="btn-primary btn-sm" onclick="changeQuantity(${p.id}, '${safeModel}', ${p.price}, 1)">+</button></div>`;
            
            const adminBtns = isAdmin 
                ? `<div style="margin-bottom:10px;"><button class="btn-primary btn-sm" style="background:#444; margin-right:5px;" onclick="openAdminModal(${p.id})">Изменить</button> <button class="btn-danger btn-sm" onclick="deleteProduct(${p.id})">Удалить</button></div>` 
                : '';

            html += `<div class="product-card" id="pc-${p.id}">
                ${img}
                <div style="font-weight:bold; color:#777; font-size:0.8rem;">${escapeHTML(p.vendor)}</div>
                <h3 class="model-name" onclick="showProductPage(${p.id})">${escapeHTML(p.model_name)}</h3>
                <p class="part-number">${escapeHTML(p.part_number)}</p>
                <div style="margin-top:auto; border-top:1px solid #eee; padding-top:1rem;">
                    ${adminBtns}
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="price">$${p.price}</span>
                        <div id="c-act-${p.id}">${btn}</div>
                    </div>
                </div>
            </div>`;
        });
        html += `</div>`;

        // --- БЛОК ПАГИНАЦИИ ---
        if (data.pages > 1) {
            html += `<div class="pagination">
                <button ${page === 1 ? 'disabled' : ''} onclick="loadCatalog(currentCategory, currentVendor, currentSearch, ${page - 1})">← Назад</button>
                <span class="page-info">Страница ${page} из ${data.pages}</span>
                <button ${page === data.pages ? 'disabled' : ''} onclick="loadCatalog(currentCategory, currentVendor, currentSearch, ${page + 1})">Вперед →</button>
            </div>`;
        }
        
        html += `</section></div>`;
        
        content.innerHTML = html;
        
        // Восстанавливаем фокус в поле поиска, если мы печатали
        if (search) {
            const searchInput = document.getElementById('search-input');
            if (searchInput) {
                searchInput.focus();
                // Ставим курсор в конец
                searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
            }
        }

    } catch(e) { 
        content.innerHTML = '<div style="color:red; text-align:center; padding: 3rem;">Ошибка загрузки каталога</div>'; 
    }
}

// Функция для поиска с задержкой (Debounce)
function handleSearch(value) {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        loadCatalog(currentCategory, currentVendor, value.trim(), 1);
    }, 400); // Ждем 400мс после последнего нажатия
}

function showProductPage(id) {
    const p = currentProducts.find(x => x.id === id);
    if (!p) return;
    
    // Собираем все картинки: главную и дополнительные
    const allImages = [];
    if (p.image_url) allImages.push(p.image_url);
    if (p.images && p.images.length) allImages.push(...p.images);
    
    const mainImgSrc = allImages.length > 0 ? escapeHTML(allImages[0]) : null;
    
    // Генерируем HTML для миниатюр
    let thumbsHtml = '';
    if (allImages.length > 1) {
        thumbsHtml = `<div class="thumbnails">`;
        allImages.forEach((img, idx) => {
            thumbsHtml += `<img src="${escapeHTML(img)}" class="thumbnail ${idx === 0 ? 'active' : ''}" onclick="switchMainImage(this, '${escapeHTML(img)}')">`;
        });
        thumbsHtml += `</div>`;
    }

    const content = document.getElementById('app-content');
    const safeModel = escapeHTML(p.model_name).replace(/'/g, "\\'");
    
    content.innerHTML = `
        <div style="padding: 1.5rem 3rem;">
            <button class="btn-primary btn-sm" style="background: #444;" onclick="loadCatalog(currentCategory, currentVendor, currentSearch, currentPage)">← Назад в каталог</button>
        </div>
        <div class="product-page-layout">
            <div class="product-page-image">
                ${mainImgSrc ? `<img src="${mainImgSrc}" class="main-img" id="main-product-img" onmousemove="zoomImage(event, this)" onmouseleave="resetZoom(this)">` : `<h2>Нет фотографии</h2>`}
            </div>
            <div class="product-page-info">
                <span style="background: var(--surface-light); padding: 4px 10px; border-radius: 4px; font-weight: bold; width: fit-content; margin-bottom: 1rem;">${escapeHTML(p.vendor)}</span>
                <h1 class="product-page-title">${escapeHTML(p.model_name)}</h1>
                <div class="product-page-pn">Part Number: ${escapeHTML(p.part_number)}</div>
                <div class="product-page-desc">${escapeHTML(p.description).replace(/\n/g, '<br>')}</div>
                <div class="product-page-price-row">
                    <div class="product-page-price">$${p.price}</div>
                    <button class="btn-primary" style="padding: 1rem 2.5rem; font-size: 1.1rem;" onclick="changeQuantity(${p.id}, '${safeModel}', ${p.price}, 1); showToast('Товар добавлен в корзину');">В корзину</button>
                </div>
            </div>
        </div>
        ${thumbsHtml}
    `;
    
    // --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    // На мобильных скроллим аккуратно к карточке, на ПК — в самый верх
    if (window.innerWidth > 768) {
        window.scrollTo(0, 0);
    } else {
        const layout = document.querySelector('.product-page-layout');
        if (layout) layout.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// Переключение главной картинки при клике на миниатюру
function switchMainImage(thumbElement, imgSrc) {
    document.getElementById('main-product-img').src = imgSrc;
    document.querySelectorAll('.thumbnail').forEach(t => t.classList.remove('active'));
    thumbElement.classList.add('active');
}

// Умный зум (следит за курсором мыши)
function zoomImage(e, img) {
    const rect = img.getBoundingClientRect();
    // Вычисляем позицию курсора в процентах
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    img.style.transformOrigin = `${x}% ${y}%`;
}

// Сброс зума, когда уводим мышку
function resetZoom(img) {
    img.style.transformOrigin = "center center";
}

// --- КОРЗИНА И ОФОРМЛЕНИЕ ЗАКАЗА ---
function updateCartCount() { 
    document.getElementById('cart-count').textContent = cart.reduce((s, i) => s + i.quantity, 0); 
}

function changeQuantity(id, model, price, delta) {
    const item = cart.find(i => i.id === id);
    if (item) {
        item.quantity += delta;
        if (item.quantity <= 0) cart = cart.filter(i => i.id !== id);
    } else if (delta > 0) {
        cart.push({ id, model, price, quantity: 1 });
    }
    localStorage.setItem('cart', JSON.stringify(cart));
    updateCartCount();
    
    const act = document.getElementById(`c-act-${id}`);
    if (act) {
        const qty = cart.find(i => i.id === id)?.quantity || 0;
        const safeModel = escapeHTML(model).replace(/'/g, "\\'");
        act.innerHTML = qty === 0 
            ? `<button class="btn-primary btn-sm" onclick="changeQuantity(${id}, '${safeModel}', ${price}, 1)">В корзину</button>`
            : `<div><button class="btn-primary btn-sm" onclick="changeQuantity(${id}, '${safeModel}', ${price}, -1)">-</button> <span style="font-weight:bold; margin:0 5px;">${qty}</span> <button class="btn-primary btn-sm" onclick="changeQuantity(${id}, '${safeModel}', ${price}, 1)">+</button></div>`;
    }
}

function showCartModal() {
    const container = document.getElementById('cart-items-container');
    container.innerHTML = '';
    let total = 0;
    if (cart.length === 0) {
        container.innerHTML = '<p style="text-align:center;">Корзина пуста</p>';
    } else {
        cart.forEach((item, idx) => {
            total += item.price * item.quantity;
            container.innerHTML += `<div style="display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #eee;">
                <div><b>${escapeHTML(item.model)}</b><br><small>${item.quantity} шт. x $${item.price}</small></div>
                <div style="display:flex; align-items:center; gap: 1rem;">
                    <b>$${item.price * item.quantity}</b>
                    <button class="btn-danger btn-sm" onclick="cart.splice(${idx},1); localStorage.setItem('cart', JSON.stringify(cart)); showCartModal(); updateCartCount();">Удалить</button>
                </div>
            </div>`;
        });
    }
    document.getElementById('cart-total-price').textContent = total;
    document.getElementById('btn-checkout').style.display = cart.length > 0 ? 'block' : 'none';
    document.getElementById('cart-modal').style.display = 'flex';
}
function closeCartModal() { document.getElementById('cart-modal').style.display = 'none'; }

async function openCheckoutModal() {
    document.getElementById('cart-modal').style.display = 'none';
    const eIn = document.getElementById('checkout-email');
    const pIn = document.getElementById('checkout-phone');
    const aIn = document.getElementById('checkout-address');
    
    eIn.value = ''; pIn.value = ''; aIn.value = ''; eIn.readOnly = false;
    
    if (localStorage.getItem('access_token')) {
        try {
            const res = await fetchAuth(`/api/profile`);
            if (res.ok) {
                const u = await res.json();
                eIn.value = u.email; eIn.readOnly = true;
                document.getElementById('checkout-email-hint').style.display = 'block';
                if (u.phone) pIn.value = u.phone;
                if (u.address) aIn.value = u.address;
            }
        } catch(e) {}
    }
    document.getElementById('checkout-modal').style.display = 'flex';
}

async function submitOrder(e) {
    e.preventDefault();
    const payload = {
        phone: document.getElementById('checkout-phone').value,
        address: document.getElementById('checkout-address').value,
        items: cart.map(i => ({ id: i.id, quantity: i.quantity })) 
    };
    
    try {
        const res = await fetchAuth('/api/checkout', { 
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify(payload) 
        });
        
        if (res.ok) {
            showToast('Заказ успешно оформлен!');
            cart = []; localStorage.setItem('cart', JSON.stringify(cart)); updateCartCount();
            document.getElementById('checkout-modal').style.display = 'none';
            if (document.querySelector('.catalog-layout')) loadCatalog(currentCategory, currentVendor, currentSearch, currentPage);
        } else {
            const err = await res.json();
            showToast(err.detail || 'Ошибка оформления', 'error');
        }
    } catch(e) { showToast('Ошибка сети', 'error'); }
}

// --- АДМИН ПАНЕЛЬ ---
function loadAdminPanel() {
    const contentDiv = document.getElementById('app-content');
    if (localStorage.getItem('user_role') !== 'admin') {
        contentDiv.innerHTML = '<div style="text-align:center; padding: 3rem; color: red;">Доступ запрещен.</div>';
        return;
    }
    contentDiv.innerHTML = `
        <div style="max-width:1200px; margin:2rem auto; padding:2rem;">
            <h2 style="color:var(--accent-crimson); margin-bottom:2rem;">Панель управления</h2>
            <div style="background:white; padding:2rem; border-radius:8px; box-shadow:var(--shadow-sm); margin-bottom:2rem;">
                <h3 style="border-bottom:2px solid var(--surface-light); padding-bottom:1rem;">Пользователи</h3>
                <div id="adm-users">Загрузка...</div>
            </div>
            <div style="background:white; padding:2rem; border-radius:8px; box-shadow:var(--shadow-sm);">
                <h3 style="border-bottom:2px solid var(--surface-light); padding-bottom:1rem;">Заказы</h3>
                <div id="adm-orders">Загрузка...</div>
            </div>
        </div>
    `;
    loadAdminUsers();
    loadAdminOrders();
}

async function loadAdminUsers() {
    try {
        const res = await fetchAuth('/api/users');
        if (!res.ok) return;
        const users = await res.json();
        let html = `<div style="overflow-x:auto;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr style="background:var(--surface-light);"><th style="padding:1rem; border-bottom:2px solid #ddd;">Email</th><th style="padding:1rem; border-bottom:2px solid #ddd;">Действия</th></tr></thead><tbody>`;
        users.forEach(u => {
            html += `<tr>
                <td style="padding:1rem; border-bottom:1px solid #eee;"><b>${escapeHTML(u.email)}</b> (${escapeHTML(u.role)})<br><small>${escapeHTML(u.phone || 'нет тел.')}</small></td>
                <td style="padding:1rem; border-bottom:1px solid #eee;">
                    <button class="btn-primary btn-sm" style="background:#444;" onclick="openEditUserModal(${u.id},'${escapeHTML(u.email)}','${escapeHTML(u.username)}','${escapeHTML(u.role)}','${escapeHTML(u.phone||'')}','${escapeHTML(u.address||'')}')">Изменить</button>
                    <button class="btn-danger btn-sm" onclick="deleteUser(${u.id})">Удалить</button>
                </td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
        document.getElementById('adm-users').innerHTML = html;
    } catch(e) {}
}

function openEditUserModal(id, e, u, r, p, a) {
    document.getElementById('edit-user-id').value = id;
    document.getElementById('edit-user-email').value = e;
    document.getElementById('edit-user-username').value = u;
    document.getElementById('edit-user-role').value = r;
    document.getElementById('edit-user-phone').value = p;
    document.getElementById('edit-user-address').value = a;
    document.getElementById('edit-user-password').value = '';
    document.getElementById('admin-user-modal').style.display = 'flex';
}

async function submitUserEdit(e) {
    e.preventDefault();
    const id = document.getElementById('edit-user-id').value;
    const payload = {
        email: document.getElementById('edit-user-email').value,
        username: document.getElementById('edit-user-username').value,
        role: document.getElementById('edit-user-role').value,
        phone: document.getElementById('edit-user-phone').value,
        address: document.getElementById('edit-user-address').value,
        password: document.getElementById('edit-user-password').value || null
    };
    try {
        const res = await fetchAuth(`/api/users/${id}`, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
        if (res.ok) {
            document.getElementById('admin-user-modal').style.display = 'none';
            showToast('Пользователь сохранен');
            loadAdminUsers();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Ошибка', 'error');
        }
    } catch (err) {}
}

async function deleteUser(id) {
    customConfirm('Удалить этого пользователя навсегда?', async () => {
        const res = await fetchAuth(`/api/users/${id}`, { method: 'DELETE' });
        if (res.ok) { showToast('Удалено'); loadAdminUsers(); }
    });
}

async function loadAdminOrders() {
    try {
        const res = await fetchAuth('/api/orders');
        if (!res.ok) return;
        const orders = await res.json();
        let html = `<div style="overflow-x:auto;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr style="background:var(--surface-light);"><th style="padding:1rem; border-bottom:2px solid #ddd;">ID / Инфо</th><th style="padding:1rem; border-bottom:2px solid #ddd;">Сумма / Статус</th><th style="padding:1rem; border-bottom:2px solid #ddd;">Действие</th></tr></thead><tbody>`;
        orders.forEach(o => {
            html += `<tr>
                <td style="padding:1rem; border-bottom:1px solid #eee;">#${o.id}<br><b>${escapeHTML(o.user_email)}</b><br><small>${escapeHTML(o.phone)}</small></td>
                <td style="padding:1rem; border-bottom:1px solid #eee;"><b>$${o.total_price}</b><br>${escapeHTML(o.status)}</td>
                <td style="padding:1rem; border-bottom:1px solid #eee;">
                    ${o.status !== 'Отменен' ? `<button class="btn-danger btn-sm" onclick="changeOrderStatus(${o.id}, 'Отменен')">Отменить</button>` : ''}
                    ${o.status === 'В обработке' ? `<button class="btn-primary btn-sm" style="background:green; margin-left: 5px;" onclick="changeOrderStatus(${o.id}, 'Доставлен')">Доставлен</button>` : ''}
                </td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
        document.getElementById('adm-orders').innerHTML = html;
    } catch(e) {}
}

async function changeOrderStatus(id, status) {
    customConfirm(`Изменить статус на "${status}"?`, async () => {
        const res = await fetchAuth(`/api/orders/${id}/status`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({status}) });
        if (res.ok) {
            showToast('Статус обновлен');
            loadAdminOrders();
        }
    });
}

// Управление товарами админом
function openAdminModal(id=null, ven='Cisco', cat='1') {
    const f = document.getElementById('admin-product-form');
    f.reset(); document.getElementById('prod-image').value = '';
    
    // Очищаем контейнер для старых фото
    const oldImagesContainer = document.getElementById('existing-images-container');
    if (oldImagesContainer) oldImagesContainer.remove();

    if (id) {
        const p = currentProducts.find(x => x.id === id);
        document.getElementById('admin-modal-title').innerText = 'Редактировать товар';
        document.getElementById('prod-id').value = p.id;
        document.getElementById('prod-vendor').value = p.vendor;
        document.getElementById('prod-category').value = p.category_id;
        document.getElementById('prod-model').value = p.model_name;
        document.getElementById('prod-pn').value = p.part_number;
        document.getElementById('prod-desc').value = p.description;
        document.getElementById('prod-price').value = p.price;
        document.getElementById('image-hint').style.display = 'block';

        // --- ВЫВОДИМ СУЩЕСТВУЮЩИЕ ФОТО ---
        if (p.images && p.images.length > 0) {
            const container = document.createElement('div');
            container.id = 'existing-images-container';
            container.style = "grid-column: 1 / -1; display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 1rem; padding: 10px; background: #f9f9f9; border-radius: 6px;";
            container.innerHTML = '<span style="width:100%; font-size:0.9rem; color:#666;">Дополнительные фото (нажмите ❌, чтобы удалить):</span>';
            
            p.images.forEach((imgUrl, index) => {
                // Нам нужно знать ID картинки в БД. 
                // Для этого в main.py при получении товаров мы добавим id картинок (см. ниже).
                // Пока используем индекс, но правильнее передавать ID.
                container.innerHTML += `
                    <div style="position:relative; width: 60px; height: 60px;">
                        <img src="${escapeHTML(imgUrl)}" style="width:100%; height:100%; object-fit:cover; border-radius:4px;">
                        <button type="button" onclick="deleteAdminImage(${p.image_ids[index]}, this)" style="position:absolute; top:-5px; right:-5px; background:red; color:white; border:none; border-radius:50%; width:20px; height:20px; cursor:pointer; font-size:10px; display:flex; align-items:center; justify-content:center;">❌</button>
                    </div>
                `;
            });
            // Вставляем перед кнопкой "Сохранить"
            const submitBtn = f.querySelector('button[type="submit"]');
            f.insertBefore(container, submitBtn);
        }
    } else {
        document.getElementById('admin-modal-title').innerText = 'Новый товар';
        document.getElementById('prod-id').value = '';
        document.getElementById('prod-vendor').value = ven;
        document.getElementById('prod-category').value = cat;
        document.getElementById('image-hint').style.display = 'none';
    }
    document.getElementById('admin-product-modal').style.display = 'flex';
}

// Функция удаления фото прямо из модалки
async function deleteAdminImage(imageId, btnElement) {
    if (!confirm("Удалить это фото?")) return;
    try {
        const res = await fetchAuth(`/api/images/${imageId}`, { method: 'DELETE' });
        if (res.ok) {
            // Визуально удаляем блок с картинкой
            btnElement.parentElement.remove();
            showToast("Фото удалено");
        } else {
            showToast("Ошибка удаления", "error");
        }
    } catch (e) {}
}

async function submitProduct(e) {
    e.preventDefault();
    const id = document.getElementById('prod-id').value;
    const fd = new FormData();
    fd.append('vendor', document.getElementById('prod-vendor').value);
    fd.append('category_id', document.getElementById('prod-category').value);
    fd.append('model_name', document.getElementById('prod-model').value);
    fd.append('part_number', document.getElementById('prod-pn').value);
    fd.append('description', document.getElementById('prod-desc').value);
    fd.append('price', document.getElementById('prod-price').value);
    
    // Берем ВСЕ выбранные файлы
    const fileInput = document.getElementById('prod-image');
    for (let i = 0; i < fileInput.files.length; i++) {
        fd.append('images', fileInput.files[i]); // Отправляем как список 'images'
    }

    const url = id ? `/api/products/${id}` : '/api/products';
    const method = id ? 'PUT' : 'POST';
    try {
        const res = await fetchAuth(url, { method: method, body: fd });
        if (res.ok) {
            document.getElementById('admin-product-modal').style.display = 'none';
            showToast('Оборудование сохранено!');
            loadCatalog(currentCategory, currentVendor, currentSearch, currentPage); 
        } else {
            const err = await res.json();
            showToast(err.detail || 'Ошибка сохранения', 'error');
        }
    } catch(e) { showToast('Ошибка сети', 'error'); }
}

async function deleteProduct(id) {
    customConfirm('Вы уверены, что хотите полностью удалить этот товар из базы данных?', async () => {
        try {
            const res = await fetchAuth(`/api/products/${id}`, { method: 'DELETE' });
            if (res.ok) {
                showToast('Оборудование удалено');
                loadCatalog(currentCategory, currentVendor, currentSearch, currentPage);
            } else {
                showToast('Ошибка при удалении', 'error');
            }
        } catch (e) {
            showToast('Ошибка сети', 'error');
        }
    });
}