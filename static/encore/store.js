/* Interfaz de la tienda: los datos y permisos siguen siendo responsabilidad del backend. */
(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const all = (selector, root = document) => [...root.querySelectorAll(selector)];
  const events = JSON.parse($('#event-data').textContent);
  const money = value => new Intl.NumberFormat('es-CL', {style: 'currency', currency: 'CLP', maximumFractionDigits: 0}).format(Number(value));
  const date = (value, options = {}) => new Intl.DateTimeFormat('es-CL', {timeZone: 'America/Santiago', ...options}).format(new Date(value));
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const fallbackImage = 'https://lumiere-a.akamaihd.net/v1/images/b577705257690e1467a1dc7e1bb8ea50_4096x2732_55e32d50.jpeg?region=0%2C0%2C4096%2C2732';
  const imageURL = value => { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; } catch { return ''; } };
  let category = 'Todos', authMode = 'login', pendingAction = null, toastTimer, cartItems = [], tickets = [];
  let session = null;
  try { session = JSON.parse(sessionStorage.getItem('encore-session')); } catch { sessionStorage.removeItem('encore-session'); }
  const list = data => Array.isArray(data) ? data : (data.results || []);
  const genre = event => /tvxq|alpha drive|ald1|k-pop|kpop|bts|blackpink|twice/i.test(event.artista + ' ' + event.nombre) ? 'K-pop' : /taylor|pop|dua lipa|ariana/i.test(event.artista + ' ' + event.nombre) ? 'Pop' : 'Otros';

  function toast(message) {
    clearTimeout(toastTimer);
    $('#toast').textContent = message;
    $('#toast').hidden = false;
    toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
  }
  function showDialog(id) {
    all('dialog[open]').forEach(dialog => dialog.close());
    $(id).showModal();
  }
  function closeDialogs() { all('dialog[open]').forEach(dialog => dialog.close()); }
  function saveSession(value) {
    session = value;
    if (value) sessionStorage.setItem('encore-session', JSON.stringify(value));
    else sessionStorage.removeItem('encore-session');
    updateAccount();
  }
  function errorText(data) {
    if (typeof data === 'string') return data;
    if (Array.isArray(data)) return data.map(errorText).join(' ');
    return Object.values(data || {}).map(errorText).join(' ') || 'No pudimos completar la operación. Intenta otra vez.';
  }
  // Renueva el acceso cuando expira; cerrar sesión borra solo las credenciales del navegador.
  async function api(path, {method = 'GET', body, authenticated = true, retry = true} = {}) {
    const headers = {'Accept': 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (authenticated && session) headers.Authorization = `Bearer ${session.access}`;
    let response;
    try { response = await fetch(`/api/${path}`, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)}); }
    catch { throw new Error('No hay conexión. Comprueba que el servidor esté funcionando.'); }
    if (response.status === 401 && authenticated && session && retry) {
      const refreshResponse = await fetch('/api/token/refresh/', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({refresh: session.refresh})});
      if (refreshResponse.ok) {
        const refreshed = await refreshResponse.json();
        saveSession({...session, access: refreshed.access, refresh: refreshed.refresh || session.refresh});
        return api(path, {method, body, authenticated, retry: false});
      }
      saveSession(null);
      throw new Error('Tu sesión terminó. Vuelve a entrar para continuar.');
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = response.status === 401 ? 'Usuario o contraseña incorrectos.' : errorText(data);
      throw new Error(message);
    }
    return data;
  }
  function updateAccount() {
    $('#account-label').textContent = session ? session.usuario.username : 'Mi cuenta';
    $('#welcome-name').textContent = session ? `Hola, ${session.usuario.username}.` : 'Mi cuenta';
    const organizer = session?.usuario.rol === 'ORGANIZADOR';
    $('#my-tickets').hidden = organizer;
    $('#orders-label').textContent = organizer ? 'Mis ventas' : 'Mis compras';
    if (!session || organizer) $('#cart-count').textContent = '0';
  }
  function requireSpectator(action) {
    if (!session) { pendingAction = action; openAuth(); return false; }
    if (session.usuario.rol !== 'ESPECTADOR') { toast('Estás usando una cuenta de organizador. Para comprar, entra con una cuenta de espectador.'); return false; }
    return true;
  }

  // Catálogo inicial renderizado por Django, con búsqueda y categorías visuales.
  const citySelect = $('#city-filter');
  [...new Set(events.map(event => event.ciudad))].sort().forEach(city => citySelect.add(new Option(city, city)));
  function renderEvents() {
    const query = $('#event-search').value.trim().toLocaleLowerCase();
    const city = citySelect.value;
    const filtered = events.filter(event => (category === 'Todos' || genre(event) === category) && (!city || event.ciudad === city) && `${event.nombre} ${event.artista}`.toLocaleLowerCase().includes(query));
    $('#event-count').textContent = `${filtered.length} ${filtered.length === 1 ? 'evento' : 'eventos'} para descubrir`;
    $('#empty-catalogue').hidden = filtered.length > 0;
    $('#event-grid').innerHTML = filtered.map(event => {
      const available = event.sectores.filter(sector => sector.stock > 0);
      const price = available.length ? Math.min(...available.map(sector => Number(sector.precio))) : null;
      return `<article class="event-card"><button type="button" class="card-image" data-event="${event.id}" aria-label="Ver ${escape(event.artista)}"><img src="${escape(imageURL(event.imagen) || fallbackImage)}" alt="${escape(event.artista)}" loading="lazy" referrerpolicy="no-referrer"><span class="card-badge">${escape(genre(event))}${event.demo ? ' · DEMO' : ''}</span><span class="date-box"><strong>${date(event.fecha, {day:'2-digit'})}</strong><span>${date(event.fecha, {month:'short'}).replace('.', '')}</span></span><span class="poster-copy"><small>${escape(event.nombre)}</small><strong>${escape(event.artista)}</strong></span></button><div class="card-body"><span class="card-meta">${date(event.fecha, {weekday:'short', day:'numeric', month:'long'})} · ${date(event.fecha, {hour:'2-digit', minute:'2-digit', hour12:false})} HRS</span><h3>${escape(event.artista)} — ${escape(event.nombre)}</h3><p class="card-location">${icon('pin')}${escape(event.recinto)} · ${escape(event.ciudad)}</p><div class="card-bottom"><span class="card-price"><small>${price === null ? 'Disponibilidad' : 'Entradas desde'}</small><strong>${price === null ? 'Agotado' : money(price)}</strong></span><button class="card-buy" type="button" data-event="${event.id}">Ver entradas ${icon('arrow')}</button></div></div></article>`;
    }).join('');
    if (!events.length) {
      $('#empty-catalogue h3').textContent = 'La próxima cartelera está en camino';
      $('#empty-catalogue p').textContent = 'Vuelve pronto para descubrir nuevos eventos.';
    }
  }
  function setCategory(value) {
    category = value;
    all('[data-category]').forEach(button => { const active = button.dataset.category === value; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); });
    renderEvents();
  }
  $('#event-search').addEventListener('input', renderEvents);
  citySelect.addEventListener('change', renderEvents);
  $('#clear-filters').addEventListener('click', () => { $('#event-search').value = ''; citySelect.value = ''; setCategory('Todos'); });

  async function openEvent(id) {
    const event = events.find(item => item.id === Number(id));
    if (!event) return;
    showDialog('#event-dialog');
    $('#event-detail').innerHTML = '<p class="loading">Buscando tu lugar en el show…</p>';
    try {
      event.sectores = list(await api(`eventos/${event.id}/sectores/`, {authenticated:false}));
      const first = event.sectores.find(sector => sector.stock > 0);
      $('#event-detail').innerHTML = `<div class="detail-banner"><img src="${escape(imageURL(event.imagen) || fallbackImage)}" alt="${escape(event.artista)}" referrerpolicy="no-referrer"><div class="poster-copy"><small>${escape(event.nombre)}${event.demo ? ' · EVENTO DEMO' : ''}</small><strong>${escape(event.artista)}</strong></div></div><div class="detail-body"><div><span class="eyebrow muted">NOS VEMOS EN PRIMERA FILA</span><h3>${escape(event.nombre)}</h3><div class="detail-meta"><span>${icon('pin')}${escape(event.recinto)} · ${escape(event.ciudad)}</span><span>${icon('ticket')}${date(event.fecha, {day:'numeric', month:'long', year:'numeric'})} · ${date(event.fecha, {hour:'2-digit', minute:'2-digit', hour12:false})} hrs</span></div><p>${escape(event.descripcion || 'Elige tu sector y prepárate para vivir una noche de música en vivo.')}</p>${event.demo ? '<div class="notice">Evento ficticio para la evaluación. La fecha, el recinto y los precios son de ejemplo.</div>' : ''}</div><form id="sector-form"><span class="eyebrow muted">ELIGE TU SECTOR</span><div style="margin-top:14px">${event.sectores.map(sector => `<label class="sector-option"><input type="radio" name="sector" value="${sector.id}" ${sector === first ? 'checked' : ''} ${sector.stock === 0 ? 'disabled' : ''} required><span>${escape(sector.nombre)}<small>${sector.stock > 0 ? `${sector.stock} disponibles` : 'Agotado'}</small></span><strong>${money(sector.precio)}</strong></label>`).join('') || '<p>No hay sectores disponibles.</p>'}</div><div class="quantity-line"><span>Cantidad de entradas</span><div class="stepper"><button type="button" data-step="-1" aria-label="Quitar una entrada">−</button><input id="ticket-quantity" type="number" min="1" max="${first?.stock || 1}" value="1" aria-label="Cantidad de entradas" required><button type="button" data-step="1" aria-label="Agregar una entrada">+</button></div></div><div class="detail-total"><span>Total</span><strong id="detail-total">${money(first?.precio || 0)}</strong></div><p class="form-error" id="sector-error" role="alert"></p><button class="button lime full" type="submit" ${first ? '' : 'disabled'}>${icon('bag')} Agregar a mi carro</button><p>La disponibilidad se confirma al completar la compra.</p></form></div>`;
      const form = $('#sector-form');
      function updateTotal() { const selected = event.sectores.find(sector => sector.id === Number(form.elements.sector.value)); const input = $('#ticket-quantity'); input.max = selected?.stock || 1; input.value = Math.min(Number(input.value) || 1, Number(input.max)); $('#detail-total').textContent = money((selected?.precio || 0) * Number(input.value)); }
      form.addEventListener('change', updateTotal);
      $('#ticket-quantity').addEventListener('input', updateTotal);
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const selected = Number(form.elements.sector.value), quantity = Number($('#ticket-quantity').value);
        const add = async () => {
          if (!requireSpectator(add)) return;
          const submit = $('button[type="submit"]', form); submit.disabled = true;
          try { await api('carro-tickets/', {method:'POST', body:{sector:selected, cantidad:quantity}}); await updateCartCount(); closeDialogs(); toast(`${quantity} ${quantity === 1 ? 'entrada agregada' : 'entradas agregadas'} a tu carro.`); await openCart(); }
          catch (error) { $('#sector-error').textContent = error.message; }
          finally { submit.disabled = false; }
        };
        await add();
      });
    } catch (error) { $('#event-detail').innerHTML = `<div class="detail-body"><div class="error-box">${escape(error.message)}</div></div>`; }
  }

  // Login y registro sin elegir privilegios: el backend asigna el rol Espectador.
  function setAuthMode(mode) {
    authMode = mode;
    const register = mode === 'register';
    $('#auth-title').textContent = register ? 'Tu próxima historia empieza aquí.' : 'Qué bueno verte.';
    $('#auth-description').textContent = register ? 'Crea tu cuenta de espectador y encuentra tu próximo concierto.' : 'Entra para guardar tu carro y encontrar tus entradas.';
    $('#email-label').hidden = !register;
    $('#auth-form').elements.email.required = register;
    $('#auth-form').elements.password.autocomplete = register ? 'new-password' : 'current-password';
    $('#auth-form').elements.password.minLength = register ? 8 : 1;
    $('#auth-submit').innerHTML = `${register ? 'Crear mi cuenta' : 'Entrar a mi cuenta'} ${icon('arrow')}`;
    $('#auth-switch-text').textContent = register ? '¿Ya tienes cuenta?' : '¿Primera vez por aquí?';
    $('#auth-toggle').textContent = register ? 'Inicia sesión' : 'Crea tu cuenta';
    $('#auth-error').textContent = '';
  }
  function openAuth() { setAuthMode('login'); showDialog('#auth-dialog'); }
  $('#auth-toggle').addEventListener('click', () => setAuthMode(authMode === 'login' ? 'register' : 'login'));
  $('#auth-form').addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.currentTarget, submit = $('#auth-submit');
    submit.disabled = true; $('#auth-error').textContent = '';
    const credentials = {username:form.elements.username.value.trim(), password:form.elements.password.value};
    let registered = false;
    try {
      if (authMode === 'register') { await api('registro/', {method:'POST', body:{...credentials, email:form.elements.email.value.trim()}, authenticated:false}); registered = true; }
      const data = await api('token/', {method:'POST', body:credentials, authenticated:false});
      saveSession(data); form.reset(); closeDialogs(); await updateCartCount();
      toast(registered ? 'Tu cuenta está lista. ¡Bienvenida a Encore!' : `Hola, ${data.usuario.username}.`);
      const action = pendingAction; pendingAction = null;
      if (action) await action();
    } catch (error) { if (registered) setAuthMode('login'); $('#auth-error').textContent = registered ? `Tu cuenta se creó. Intenta iniciar sesión. ${error.message}` : error.message; }
    finally { submit.disabled = false; }
  });
  $('#account-button').addEventListener('click', () => session ? showDialog('#account-dialog') : openAuth());
  $('#logout-button').addEventListener('click', () => { saveSession(null); cartItems = []; pendingAction = null; closeDialogs(); toast('Sesión cerrada. Tu carro sigue guardado en tu cuenta.'); });
  async function updateCartCount() {
    if (!session || session.usuario.rol !== 'ESPECTADOR') return;
    try { cartItems = list(await api('carro-tickets/')); $('#cart-count').textContent = String(cartItems.reduce((total, item) => total + item.cantidad, 0)); }
    catch (error) { toast(error.message); }
  }
  function startDrawer(title, eyebrow) { $('#drawer-title').textContent = title; $('#drawer-eyebrow').textContent = eyebrow; $('#drawer-content').innerHTML = '<p class="loading">Un momento, estamos preparando todo…</p>'; showDialog('#drawer-dialog'); }
  function drawerEmpty(title, text) { return `<div class="drawer-empty">${icon('ticket')}<h3>${escape(title)}</h3><p>${escape(text)}</p><button class="button lime" type="button" data-explore>Explorar eventos ${icon('arrow')}</button></div>`; }
  async function openCart() {
    if (!requireSpectator(openCart)) return;
    startDrawer('Mi carro', 'UN PASO MÁS CERCA');
    try {
      cartItems = list(await api('carro-tickets/'));
      $('#cart-count').textContent = String(cartItems.reduce((total, item) => total + item.cantidad, 0));
      if (!cartItems.length) { $('#drawer-content').innerHTML = drawerEmpty('Tu próximo plan te espera.', 'Todavía no tienes entradas en tu carro.'); return; }
      const total = cartItems.reduce((sum, item) => sum + Number(item.precio_unitario) * item.cantidad, 0);
      $('#drawer-content').innerHTML = `${cartItems.map(item => `<article class="cart-item"><div class="cart-item-icon">${icon('ticket')}</div><div class="cart-item-info"><h3>${escape(item.evento_nombre)}</h3><p>${escape(item.sector_nombre)} · ${item.cantidad} ${item.cantidad === 1 ? 'entrada' : 'entradas'}</p><div class="cart-item-bottom"><strong>${money(Number(item.precio_unitario) * item.cantidad)}</strong><button type="button" class="remove-item" data-remove="${item.id}">Quitar</button></div></div></article>`).join('')}<div class="cart-summary"><span>Total de tu carro</span><strong>${money(total)}</strong></div><div class="notice">Las entradas aún no están reservadas. Confirmaremos la disponibilidad y el precio al comprar.</div><form id="checkout-form"><label class="payment-label"><input type="checkbox" required>Comprendo que es una compra de prueba, sin cobro real ni validez para ingresar a un concierto.</label><p id="checkout-error" class="form-error" role="alert"></p><button class="button lime full" type="submit">Confirmar compra de prueba ${icon('arrow')}</button></form>`;
      $('#checkout-form').addEventListener('submit', async e => {
        e.preventDefault(); const submit = $('button[type="submit"]', e.currentTarget); submit.disabled = true;
        try {
          const purchases = await api('compras/pagar/', {method:'POST'});
          const count = purchases.reduce((sum, purchase) => sum + purchase.detalles.reduce((subtotal, detail) => subtotal + detail.entradas.length, 0), 0);
          await updateCartCount();
          $('#drawer-title').textContent = '¡Ya tienes tu lugar!';
          $('#drawer-content').innerHTML = `<div class="success-panel"><div class="success-circle">${icon('check')}</div><h3>Nos vemos en primera fila.</h3><p>Tu compra de prueba se completó.<br>${count} ${count === 1 ? 'entrada está lista' : 'entradas están listas'} en tu cuenta.</p><button class="button lime" type="button" data-show-tickets>Ver mis entradas ${icon('ticket')}</button></div><div class="notice">No se realizó ningún cobro. Los tickets de demostración no tienen validez para eventos reales.</div>`;
          await refreshStock();
        } catch (error) { $('#checkout-error').textContent = error.message; submit.disabled = false; }
      });
    } catch (error) { $('#drawer-content').innerHTML = `<div class="error-box">${escape(error.message)}</div>`; }
  }
  async function refreshStock() {
    await Promise.all(events.map(async event => { try { event.sectores = list(await api(`eventos/${event.id}/sectores/`, {authenticated:false})); } catch { /* El evento puede haber sido desactivado. */ } }));
    renderEvents();
  }
  async function openTickets() {
    if (!requireSpectator(openTickets)) return;
    startDrawer('Mis entradas', 'TUS PRÓXIMOS RECUERDOS');
    try {
      tickets = list(await api('mis-entradas/'));
      $('#drawer-content').innerHTML = tickets.length ? tickets.map(ticket => `<article class="ticket-card"><div class="ticket-top"><span>ENCORE · ENTRADA</span>${icon('ticket')}</div><div class="ticket-body"><h3>${escape(ticket.evento)}</h3><p>${escape(ticket.sector)}</p><code class="ticket-code">${escape(ticket.codigo)}</code><span class="ticket-status ${ticket.valida ? '' : 'invalid'}">${!ticket.valida ? 'Compra cancelada · entrada inválida' : ticket.utilizada ? 'Ingreso registrado' : 'Entrada disponible'}</span><button class="ticket-download" type="button" data-download="${ticket.id}">Guardar comprobante</button></div></article>`).join('') : drawerEmpty('El mejor recuerdo está por venir.', 'Tus entradas aparecerán aquí después de comprar.');
    } catch (error) { $('#drawer-content').innerHTML = `<div class="error-box">${escape(error.message)}</div>`; }
  }
  async function openOrders() {
    if (!session) { pendingAction = openOrders; openAuth(); return; }
    const organizer = session.usuario.rol === 'ORGANIZADOR';
    startDrawer(organizer ? 'Mis ventas' : 'Mis compras', organizer ? 'LA MÚSICA TAMBIÉN SE ORGANIZA' : 'TU HISTORIA EN ENCORE');
    try {
      const orders = list(await api('compras/'));
      $('#drawer-content').innerHTML = orders.length ? orders.map(order => `<article class="order-card"><header><strong>Compra #${order.id}</strong><span class="order-status">${escape(order.estado)}</span></header><p>${date(order.creada, {day:'numeric', month:'long', year:'numeric'})}</p><p>${order.detalles.map(detail => `${detail.cantidad} ${detail.cantidad === 1 ? 'entrada' : 'entradas'} · ${escape(detail.entradas[0]?.evento || 'Evento')}`).join('<br>')}</p><strong>${money(order.total)}</strong>${organizer && order.estado === 'PAGADO' ? `<div class="order-actions"><button type="button" data-order="${order.id}" data-status="ENTREGADO">Marcar ingreso</button><button type="button" data-order="${order.id}" data-status="CANCELADO">Cancelar compra</button></div>` : ''}</article>`).join('') : drawerEmpty(organizer ? 'Tus ventas aparecerán aquí.' : 'Tu primera compra te espera.', organizer ? 'Cuando un espectador compre entradas de tus eventos, podrás gestionar su compra.' : 'Encuentra un concierto y vive la música de cerca.');
    } catch (error) { $('#drawer-content').innerHTML = `<div class="error-box">${escape(error.message)}</div>`; }
  }
  $('#cart-button').addEventListener('click', openCart);
  $('#my-tickets').addEventListener('click', openTickets);
  $('#footer-tickets').addEventListener('click', openTickets);
  $('#my-orders').addEventListener('click', openOrders);
  $('#help-button').addEventListener('click', () => showDialog('#help-dialog'));

  // Delegación de acciones para tarjetas y paneles que se actualizan dinámicamente.
  document.addEventListener('click', async e => {
    const button = e.target.closest('button');
    if (!button) return;
    if (button.hasAttribute('data-close')) { button.closest('dialog').close(); return; }
    if (button.dataset.category) setCategory(button.dataset.category);
    if (button.dataset.filterLink) { setCategory(button.dataset.filterLink); $('#cartelera').scrollIntoView({behavior:'smooth'}); }
    if (button.dataset.event) await openEvent(button.dataset.event);
    if (button.hasAttribute('data-explore')) { closeDialogs(); $('#cartelera').scrollIntoView({behavior:'smooth'}); }
    if (button.hasAttribute('data-show-tickets')) await openTickets();
    if (button.dataset.step) { const input = $('#ticket-quantity'); input.value = Math.max(1, Math.min(Number(input.max), Number(input.value) + Number(button.dataset.step))); input.dispatchEvent(new Event('input')); }
    if (button.dataset.remove) {
      button.disabled = true;
      try { await api(`carro-tickets/${button.dataset.remove}/`, {method:'DELETE'}); await openCart(); }
      catch (error) { toast(error.message); button.disabled = false; }
    }
    if (button.dataset.order) {
      const cancel = button.dataset.status === 'CANCELADO';
      if (!window.confirm(cancel ? '¿Cancelar esta compra y devolver las entradas disponibles?' : '¿Marcar todas las entradas de esta compra como utilizadas?')) return;
      button.disabled = true;
      try { await api(`compras/${button.dataset.order}/estado/`, {method:'PATCH', body:{estado:button.dataset.status}}); await openOrders(); await refreshStock(); toast(cancel ? 'Compra cancelada. Stock restituido.' : 'Ingreso registrado.'); }
      catch (error) { toast(error.message); button.disabled = false; }
    }
    if (button.dataset.download) {
      const ticket = tickets.find(item => item.id === Number(button.dataset.download));
      const text = `ENCORE · COMPROBANTE ACADÉMICO\n\nEvento: ${ticket.evento}\nSector: ${ticket.sector}\nCódigo: ${ticket.codigo}\nEstado: ${!ticket.valida ? 'Cancelada' : ticket.utilizada ? 'Utilizada' : 'Disponible'}\n\nProyecto académico. Este comprobante no tiene validez para eventos reales.`;
      const url = URL.createObjectURL(new Blob([text], {type:'text/plain;charset=utf-8'}));
      const link = document.createElement('a'); link.href = url; link.download = `encore-entrada-${ticket.id}.txt`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  });
  all('dialog').forEach(dialog => dialog.addEventListener('click', e => { if (e.target !== dialog) return; const rect = dialog.getBoundingClientRect(); if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) dialog.close(); }));
  updateAccount(); renderEvents(); updateCartCount();
})();
