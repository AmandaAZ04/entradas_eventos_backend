/* Interfaz de la tienda: los datos y permisos siguen siendo responsabilidad del backend. */
(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const all = (selector, root = document) => [
    ...root.querySelectorAll(selector),
  ];
  const events = JSON.parse($("#event-data").textContent);
  const money = (value) =>
    new Intl.NumberFormat("es-CL", {
      style: "currency",
      currency: "CLP",
      maximumFractionDigits: 0,
    }).format(Number(value));
  const date = (value, options = {}) =>
    new Intl.DateTimeFormat("es-CL", {
      timeZone: "America/Santiago",
      ...options,
    }).format(new Date(value));
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const icon = (name) =>
    `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const fallbackImage =
    "https://lumiere-a.akamaihd.net/v1/images/b577705257690e1467a1dc7e1bb8ea50_4096x2732_55e32d50.jpeg?region=0%2C0%2C4096%2C2732";
  const imageURL = (value) => {
    try {
      const url = new URL(value);
      return ["https:", "http:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  };
  let category = "Todos",
    authMode = "login",
    pendingAction = null,
    toastTimer,
    cartItems = [],
    tickets = [];
  let session = null;
  try {
    session = JSON.parse(sessionStorage.getItem("encore-session"));
  } catch {
    sessionStorage.removeItem("encore-session");
  }
  const list = (data) => (Array.isArray(data) ? data : data.results || []);
  const genre = (event) => event.categoria || "Otros eventos";
  const paymentEnvironment = JSON.parse($("#payment-environment").textContent);

  function toast(message) {
    clearTimeout(toastTimer);
    $("#toast").textContent = message;
    $("#toast").hidden = false;
    toastTimer = setTimeout(() => {
      $("#toast").hidden = true;
    }, 4500);
  }
  function showDialog(id) {
    all("dialog[open]").forEach((dialog) => dialog.close());
    $(id).showModal();
  }
  function closeDialogs() {
    all("dialog[open]").forEach((dialog) => dialog.close());
  }
  function saveSession(value) {
    session = value;
    if (value) sessionStorage.setItem("encore-session", JSON.stringify(value));
    else sessionStorage.removeItem("encore-session");
    updateAccount();
  }
  function errorText(data) {
    if (typeof data === "string") return data;
    if (Array.isArray(data)) return data.map(errorText).join(" ");
    return (
      Object.values(data || {})
        .map(errorText)
        .join(" ") || "No pudimos completar la operación. Intenta otra vez."
    );
  }
  // Renueva el acceso cuando expira; cerrar sesión borra solo las credenciales del navegador.
  async function api(
    path,
    { method = "GET", body, authenticated = true, retry = true } = {},
  ) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (authenticated && session)
      headers.Authorization = `Bearer ${session.access}`;
    let response;
    try {
      response = await fetch(`/api/${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new Error(
        "No hay conexión. Comprueba que el servidor esté funcionando.",
      );
    }
    if (response.status === 401 && authenticated && session && retry) {
      const refreshResponse = await fetch("/api/token/refresh/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: session.refresh }),
      });
      if (refreshResponse.ok) {
        const refreshed = await refreshResponse.json();
        saveSession({
          ...session,
          access: refreshed.access,
          refresh: refreshed.refresh || session.refresh,
        });
        return api(path, { method, body, authenticated, retry: false });
      }
      saveSession(null);
      throw new Error("Tu sesión terminó. Vuelve a entrar para continuar.");
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message =
        response.status === 401
          ? "Usuario o contraseña incorrectos."
          : errorText(data);
      const error = new Error(message);
      error.fields = data;
      throw error;
    }
    return data;
  }
  function updateAccount() {
    $("#account-label").textContent = session
      ? session.usuario.nombres || session.usuario.username
      : "Mi cuenta";
    $("#welcome-name").textContent = session
      ? `Hola, ${session.usuario.nombres || session.usuario.username}.`
      : "Mi cuenta";
    const organizer = session?.usuario.rol === "ORGANIZADOR";
    $("#my-tickets").hidden = organizer;
    $("#my-events").hidden = !organizer;
    $("#account-role").textContent = organizer
      ? "Cuenta de organizador"
      : "Cuenta de espectador";
    $("#organizer-access").textContent = organizer
      ? "Mi panel"
      : "Organizadores";
    $("#cart-button").hidden = organizer;
    $("#orders-label").textContent = organizer ? "Mis ventas" : "Mis compras";
    if (!session || organizer) $("#cart-count").textContent = "0";
  }
  function requireSpectator(action) {
    if (!session) {
      pendingAction = action;
      openAuth();
      return false;
    }
    if (session.usuario.rol !== "ESPECTADOR") {
      toast(
        "Estás usando una cuenta de organizador. Para comprar, entra con una cuenta de espectador.",
      );
      return false;
    }
    return true;
  }

  // Catálogo inicial renderizado por Django, con búsqueda y categorías visuales.
  const citySelect = $("#city-filter");
  [...new Set(events.map((event) => event.ciudad))]
    .sort()
    .forEach((city) => citySelect.add(new Option(city, city)));
  function renderEvents() {
    const query = $("#event-search").value.trim().toLocaleLowerCase();
    const city = citySelect.value;
    const filtered = events.filter(
      (event) =>
        (category === "Todos" || genre(event) === category) &&
        (!city || event.ciudad === city) &&
        `${event.nombre} ${event.artista}`.toLocaleLowerCase().includes(query),
    );
    $("#event-count").textContent =
      `${filtered.length} ${filtered.length === 1 ? "evento" : "eventos"} para descubrir`;
    $("#empty-catalogue").hidden = filtered.length > 0;
    $("#event-grid").innerHTML = filtered
      .map((event) => {
        const available = event.sectores.filter((sector) => sector.stock > 0);
        const price = available.length
          ? Math.min(...available.map((sector) => Number(sector.precio)))
          : null;
        return `<article class="event-card"><button type="button" class="card-image" data-event="${event.id}" aria-label="Ver ${escape(event.artista)}"><img src="${escape(imageURL(event.imagen) || fallbackImage)}" alt="${escape(event.artista)}" loading="lazy" referrerpolicy="no-referrer"><span class="card-badge">${escape(genre(event))}</span><span class="date-box"><strong>${date(event.fecha, { day: "2-digit" })}</strong><span>${date(event.fecha, { month: "short" }).replace(".", "")}</span></span><span class="poster-copy"><small>${escape(event.nombre)}</small><strong>${escape(event.artista)}</strong></span></button><div class="card-body"><span class="card-meta">${date(event.fecha, { weekday: "short", day: "numeric", month: "long" })} · ${date(event.fecha, { hour: "2-digit", minute: "2-digit", hour12: false })} HRS</span><h3>${escape(event.artista)} — ${escape(event.nombre)}</h3><p class="card-location">${icon("pin")}${escape(event.recinto)} · ${escape(event.ciudad)}</p><div class="card-bottom"><span class="card-price"><small>${price === null ? "Disponibilidad" : "Entradas desde"}</small><strong>${price === null ? "Agotado" : money(price)}</strong></span><button class="card-buy" type="button" data-event="${event.id}">Ver entradas ${icon("arrow")}</button></div></div></article>`;
      })
      .join("");
    $("#empty-catalogue h3").textContent =
      query || city
        ? "No encontramos eventos para tu búsqueda."
        : "Lo sentimos, no tenemos eventos disponibles de momento.";
    $("#empty-catalogue p").textContent =
      query || city
        ? "Prueba con otro artista, ciudad o categoría."
        : "Estamos preparando nuevos panoramas. Vuelve pronto o explora otra categoría.";
  }
  function setCategory(value) {
    category = value;
    $("#category-filter").value = value;
    all("[data-category]").forEach((button) => {
      const active = button.dataset.category === value;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderEvents();
  }
  $("#event-search").addEventListener("input", renderEvents);
  citySelect.addEventListener("change", renderEvents);
  $("#category-filter").addEventListener("change", (e) =>
    setCategory(e.target.value),
  );
  $("#clear-filters").addEventListener("click", () => {
    $("#event-search").value = "";
    citySelect.value = "";
    setCategory("Todos");
  });

  // El plano comparte geometría; cada cuadradito conserva su ID del evento.
  async function openEvent(id) {
    const event = events.find((item) => item.id === Number(id));
    if (!event) return;
    showDialog("#event-dialog");
    $("#event-detail").innerHTML =
      '<p class="loading">Estamos buscando tu lugar en el show…</p>';
    try {
      event.sectores = list(
        await api(`eventos/${event.id}/asientos/`, { authenticated: false }),
      );
      let current =
        event.sectores.find((s) => s.stock > 0) || event.sectores[0];
      let chosen = new Set();
      const zoneClass = (s) =>
        /vip/i.test(s.nombre)
          ? "zone-vip"
          : /tribuna/i.test(s.nombre)
            ? "zone-tribuna"
            : "zone-cancha";
      const dots = (x, y, columns, rows, color) =>
        Array.from(
          { length: columns * rows },
          (_, i) =>
            `<rect x="${x + (i % columns) * 12}" y="${y + Math.floor(i / columns) * 12}" width="7" height="7" rx="2" fill="${color}"/>`,
        ).join("");
      const overview = `<div class="arena-overview" aria-label="Plano del recinto"><svg viewBox="0 0 600 350" aria-hidden="true"><rect x="22" y="10" width="556" height="326" rx="155" fill="#e7e1f1"/><rect x="52" y="32" width="496" height="277" rx="128" fill="none" stroke="#c9bcdd" stroke-width="2"/><rect x="76" y="48" width="448" height="245" rx="113" fill="none" stroke="#c9bcdd" stroke-width="2"/><rect x="106" y="64" width="388" height="213" rx="92" fill="#fafbf8"/><rect x="226" y="30" width="148" height="48" rx="9" fill="#24332b"/><text x="300" y="59" text-anchor="middle" fill="white" font-size="13" font-family="sans-serif" letter-spacing="2">ESCENARIO</text><rect x="204" y="99" width="192" height="64" rx="14" fill="#f8e9c6"/>${dots(222, 109, 14, 4, "#dab665")}<rect x="185" y="177" width="230" height="87" rx="14" fill="#e0efdf"/>${dots(205, 190, 16, 5, "#91b99a")}${dots(67, 113, 3, 10, "#b9a2d4")}${dots(502, 113, 3, 10, "#b9a2d4")}${dots(178, 292, 21, 2, "#b9a2d4")}</svg>${event.sectores.map((s) => `<button type="button" class="arena-zone ${zoneClass(s)}" data-zone="${s.id}" aria-pressed="false">${escape(s.nombre)}<small>${money(s.precio)}</small></button>`).join("")}</div>`;
      $("#event-detail").innerHTML =
        `<div class="seat-event-header"><img src="${escape(imageURL(event.imagen) || fallbackImage)}" alt="${escape(event.artista)}" referrerpolicy="no-referrer"><div><span class="eyebrow muted">TU PRÓXIMA NOCHE INOLVIDABLE</span><h2>${escape(event.artista)}</h2><p>${escape(event.nombre)}</p><div class="detail-meta"><span>${icon("pin")}${escape(event.recinto)} · ${escape(event.ciudad)}</span><span>${date(event.fecha, { day: "numeric", month: "long", year: "numeric" })} · ${date(event.fecha, { hour: "2-digit", minute: "2-digit", hour12: false })} hrs</span></div></div></div><div class="seat-layout"><div class="seat-map-column"><div class="seat-section-heading"><div><span class="eyebrow muted">01 / ENCUENTRA TU ZONA</span><h3>La mejor vista empieza aquí.</h3></div><span class="map-pill">Plano del recinto</span></div>${overview}<div class="zone-legend">${event.sectores.map((s) => `<button type="button" class="zone-chip ${zoneClass(s)}" data-zone="${s.id}"><span></span>${escape(s.nombre)}</button>`).join("")}</div><div class="seat-section-heading seat-grid-heading"><div><span class="eyebrow muted">02 / ELIGE TUS ASIENTOS</span><h3 id="seat-zone-title"></h3></div><strong id="seat-zone-price"></strong></div><div class="seat-key"><span><i class="key-free"></i>Disponible</span><span><i class="key-selected"></i>Tu selección</span><span><i class="key-unavailable"></i>Ocupado</span></div><div class="seat-grid-wrap"><div class="stage-direction">↑ MIRANDO AL ESCENARIO</div><div id="seat-grid" class="seat-grid" role="group" aria-label="Asientos disponibles"></div></div><p class="seat-help">Toca un cuadradito para elegir tu silla. Máximo 20 asientos por zona.</p></div><form id="sector-form" class="seat-summary"><span class="eyebrow muted">03 / TU PRÓXIMO RECUERDO</span><h3>Tu selección</h3><p id="selection-zone"></p><div id="selected-seats" class="selected-seats" aria-live="polite"></div><div class="selection-count"><span>Entradas</span><strong id="seat-count">0</strong></div><div class="detail-total"><span>Total</span><strong id="detail-total">${money(0)}</strong></div><p class="form-error" id="sector-error" role="alert"></p><button id="seat-add" class="button lime full" type="submit" disabled>${icon("bag")} Agregar a mi carro</button><p class="seat-summary-note">Guardamos tu selección en tu cuenta. Tus asientos se confirman al completar el pago.</p><button class="text-link" type="button" data-close>Seguir explorando</button></form></div>`;
      const root = $("#event-detail"),
        form = $("#sector-form");
      function updateSelection() {
        const seats = (current?.asientos || []).filter((s) => chosen.has(s.id));
        $("#selection-zone").textContent =
          current?.nombre || "Sin localidades disponibles";
        $("#selected-seats").innerHTML = seats.length
          ? seats
              .map(
                (s) =>
                  `<span class="seat-token">Fila ${escape(s.fila)} · ${s.numero}<button type="button" data-unselect="${s.id}" aria-label="Quitar asiento ${escape(s.etiqueta)}">×</button></span>`,
              )
              .join("")
          : '<div class="no-seats-selected">Tu lugar en el show te espera.<small>Selecciona tus asientos en el mapa.</small></div>';
        $("#seat-count").textContent = String(seats.length);
        $("#detail-total").textContent = money(
          (current?.precio || 0) * seats.length,
        );
        $("#seat-add").disabled = !seats.length;
        all("[data-seat]", root).forEach((button) => {
          const selected = chosen.has(Number(button.dataset.seat));
          button.classList.toggle("selected", selected);
          button.setAttribute("aria-pressed", String(selected));
        });
      }
      function renderZone() {
        $("#seat-zone-title").textContent =
          current?.nombre || "No hay sectores disponibles";
        $("#seat-zone-price").textContent = current
          ? `${money(current.precio)} / entrada`
          : "";
        all("[data-zone]", root).forEach((button) => {
          const selected = Number(button.dataset.zone) === current?.id;
          button.classList.toggle("active", selected);
          button.setAttribute("aria-pressed", String(selected));
        });
        const rows = new Map();
        (current?.asientos || []).forEach((seat) => {
          if (!rows.has(seat.fila)) rows.set(seat.fila, []);
          rows.get(seat.fila).push(seat);
        });
        $("#seat-grid").className =
          `seat-grid ${current ? zoneClass(current) : ""}`;
        $("#seat-grid").innerHTML = rows.size
          ? [...rows]
              .map(
                ([row, seats]) =>
                  `<div class="seat-row"><span class="seat-row-label">${escape(row)}</span><div class="seat-row-buttons">${seats.map((seat) => `<button type="button" class="seat-square" data-seat="${seat.id}" aria-label="${escape(current.nombre)}, fila ${escape(row)}, asiento ${seat.numero}${seat.disponible ? "" : ", ocupado"}" aria-pressed="false" title="Fila ${escape(row)} · Asiento ${seat.numero}" ${seat.disponible ? "" : "disabled"}>${seat.numero}</button>`).join("")}</div><span class="seat-row-label">${escape(row)}</span></div>`,
              )
              .join("")
          : '<p class="loading">Esta zona todavía no tiene asientos configurados.</p>';
        updateSelection();
      }
      root.onclick = (e) => {
        const zone = e.target.closest("[data-zone]"),
          seat = e.target.closest("[data-seat]"),
          remove = e.target.closest("[data-unselect]");
        if (zone) {
          const next = event.sectores.find(
            (s) => s.id === Number(zone.dataset.zone),
          );
          if (next?.id !== current?.id) {
            current = next;
            chosen.clear();
            $("#sector-error").textContent = "";
            renderZone();
          }
        }
        if (seat && !seat.disabled) {
          const key = Number(seat.dataset.seat);
          if (chosen.has(key)) chosen.delete(key);
          else if (chosen.size < Math.min(20, current.stock)) chosen.add(key);
          else {
            $("#sector-error").textContent =
              "Alcanzaste el máximo disponible para esta zona.";
            return;
          }
          $("#sector-error").textContent = "";
          updateSelection();
        }
        if (remove) {
          chosen.delete(Number(remove.dataset.unselect));
          updateSelection();
        }
      };
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const body = {
          sector: current.id,
          cantidad: chosen.size,
          asientos: [...chosen],
        };
        const add = async () => {
          if (!requireSpectator(add)) return;
          const submit = $("#seat-add");
          submit.disabled = true;
          try {
            await api("carro-tickets/", { method: "POST", body });
            await updateCartCount();
            closeDialogs();
            toast("Tus asientos se agregaron al carro.");
            await openCart();
          } catch (error) {
            $("#sector-error").textContent = error.message;
          } finally {
            submit.disabled = false;
          }
        };
        if (chosen.size) await add();
      });
      renderZone();
    } catch (error) {
      $("#event-detail").innerHTML =
        `<div class="detail-body"><div class="error-box">${escape(error.message)}</div></div>`;
    }
  }

  // Registro: las mismas reglas se comprueban de nuevo en el servidor.
  const authForm = $("#auth-form");
  const passwordRules = (value) => ({
    length: value.length >= 8 && value.length <= 16,
    spaces: value.length > 0 && !/\s/.test(value),
    case: /\p{Lu}/u.test(value) && /\p{Ll}/u.test(value),
    special: /[@$#*]/.test(value),
    number: /[0-9]/.test(value),
  });
  function checkPassword() {
    const rules = passwordRules(authForm.elements.password.value);
    all("[data-rule]").forEach((item) =>
      item.classList.toggle("valid", rules[item.dataset.rule]),
    );
    return Object.values(rules).every(Boolean);
  }
  function checkRut(value) {
    const rut = value.trim().replace(/[.\-]/g, "").toUpperCase();
    if (!/^[1-9][0-9]{0,7}[0-9K]$/.test(rut)) return false;
    const number = rut.slice(0, -1),
      sum = [...number]
        .reverse()
        .reduce((total, digit, i) => total + Number(digit) * (2 + (i % 6)), 0);
    const digit = 11 - (sum % 11);
    return (
      rut.at(-1) === (digit === 11 ? "0" : digit === 10 ? "K" : String(digit))
    );
  }
  function clearAuthErrors() {
    $("#auth-error").textContent = "";
    all("[data-error]").forEach((item) => (item.textContent = ""));
    all("input", authForm).forEach((input) =>
      input.removeAttribute("aria-invalid"),
    );
  }
  function showFieldErrors(errors) {
    Object.entries(errors).forEach(([name, value]) => {
      const target = $(`[data-error="${name}"]`);
      if (target) {
        target.textContent = errorText(value);
        authForm.elements[name]?.setAttribute("aria-invalid", "true");
      }
    });
  }
  function toggleDocument() {
    const foreign = authForm.elements.extranjero.checked,
      register = authMode === "register";
    $("#rut-label").hidden = foreign;
    $("#document-label").hidden = !foreign;
    authForm.elements.rut.disabled = !register || foreign;
    authForm.elements.rut.required = register && !foreign;
    authForm.elements.documento_extranjero.disabled = !register || !foreign;
    authForm.elements.documento_extranjero.required = register && foreign;
  }
  function setAuthMode(mode) {
    if (authMode !== mode) {
      authForm.elements.password.value = "";
      authForm.elements.password.type = "password";
      $("#password-toggle").textContent = "Ver";
      $("#password-toggle").setAttribute("aria-label", "Mostrar contraseña");
      $("#password-toggle").setAttribute("aria-pressed", "false");
    }
    authMode = mode;
    const register = mode === "register";
    $("#auth-title").textContent = register
      ? "Crea tu cuenta."
      : "Qué bueno verte.";
    $("#auth-description").textContent = register
      ? "Ingresa tus datos y ahorra tiempo en tu próxima compra."
      : "Entra para guardar tu carro y encontrar tus entradas.";
    $("#username-label").hidden = register;
    authForm.elements.username.disabled = register;
    authForm.elements.username.required = !register;
    $("#registration-fields").hidden = !register;
    $("#password-rules").hidden = !register;
    ["nombres", "apellido_paterno", "email", "extranjero"].forEach((name) => {
      authForm.elements[name].disabled = !register;
      authForm.elements[name].required = register && name !== "extranjero";
    });
    toggleDocument();
    authForm.elements.password.autocomplete = register
      ? "new-password"
      : "current-password";
    authForm.elements.password.minLength = register ? 8 : 1;
    authForm.elements.password.maxLength = register ? 16 : 128;
    $("#auth-submit").innerHTML =
      `${register ? "Registrar" : "Entrar a mi cuenta"} ${icon("arrow")}`;
    $("#auth-switch-text").textContent = register
      ? "¿Ya tienes cuenta?"
      : "¿Primera vez por aquí?";
    $("#auth-toggle").textContent = register
      ? "Inicia sesión"
      : "Crea tu cuenta";
    clearAuthErrors();
    checkPassword();
  }
  function openAuth() {
    $(".auth-switch").hidden = false;
    setAuthMode("login");
    showDialog("#auth-dialog");
  }
  authForm.elements.extranjero.addEventListener("change", toggleDocument);
  authForm.elements.password.addEventListener("input", checkPassword);
  $("#password-toggle").addEventListener("click", (e) => {
    const visible = authForm.elements.password.type === "password";
    authForm.elements.password.type = visible ? "text" : "password";
    e.currentTarget.textContent = visible ? "Ocultar" : "Ver";
    e.currentTarget.setAttribute(
      "aria-label",
      visible ? "Ocultar contraseña" : "Mostrar contraseña",
    );
    e.currentTarget.setAttribute("aria-pressed", String(visible));
  });
  $("#auth-toggle").addEventListener("click", () =>
    setAuthMode(authMode === "login" ? "register" : "login"),
  );
  authForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearAuthErrors();
    const form = e.currentTarget,
      submit = $("#auth-submit"),
      register = authMode === "register";
    const credentials = {
      username: register
        ? form.elements.email.value.trim()
        : form.elements.username.value.trim(),
      password: form.elements.password.value,
    };
    const errors = {};
    if (register) {
      ["nombres", "apellido_paterno"].forEach((name) => {
        if (
          !/^[\p{L}][\p{L} '\u2019-]*$/u.test(form.elements[name].value.trim())
        )
          errors[name] = "Escribe solo letras, espacios, guiones o apóstrofos.";
      });
      if (!checkPassword())
        errors.password =
          "Tu contraseña debe cumplir todas las reglas indicadas.";
      if (
        !form.elements.extranjero.checked &&
        !checkRut(form.elements.rut.value)
      )
        errors.rut = "Ingresa un RUT válido. Revisa el dígito verificador.";
      if (
        form.elements.extranjero.checked &&
        !/^[A-Z0-9-]{5,30}$/i.test(
          form.elements.documento_extranjero.value.trim(),
        )
      )
        errors.documento_extranjero =
          "Ingresa un documento de 5 a 30 letras o números.";
      if (Object.keys(errors).length) {
        showFieldErrors(errors);
        $("#auth-error").textContent =
          "Revisa los campos indicados para continuar.";
        return;
      }
    }
    submit.disabled = true;
    let registered = false;
    try {
      if (register) {
        const body = {
          email: form.elements.email.value.trim(),
          password: credentials.password,
          nombres: form.elements.nombres.value.trim(),
          apellido_paterno: form.elements.apellido_paterno.value.trim(),
          extranjero: form.elements.extranjero.checked,
        };
        if (body.extranjero)
          body.documento_extranjero =
            form.elements.documento_extranjero.value.trim();
        else body.rut = form.elements.rut.value.trim();
        await api("registro/", { method: "POST", body, authenticated: false });
        registered = true;
      }
      const data = await api("token/", {
        method: "POST",
        body: credentials,
        authenticated: false,
      });
      saveSession(data);
      form.reset();
      closeDialogs();
      await updateCartCount();
      toast(
        registered
          ? "Tu cuenta está lista. ¡Bienvenida a Encore!"
          : `Hola, ${data.usuario.nombres || data.usuario.username}.`,
      );
      const action = pendingAction;
      pendingAction = null;
      if (action) await action();
      else if (data.usuario.rol === "ORGANIZADOR") await openOrganizer();
    } catch (error) {
      if (registered) setAuthMode("login");
      else showFieldErrors(error.fields || {});
      $("#auth-error").textContent = registered
        ? `Tu cuenta se creó. Inicia sesión con tu email. ${error.message}`
        : error.message;
    } finally {
      submit.disabled = false;
    }
  });
  $("#account-button").addEventListener("click", () =>
    session ? showDialog("#account-dialog") : openAuth(),
  );
  $("#logout-button").addEventListener("click", () => {
    saveSession(null);
    cartItems = [];
    pendingAction = null;
    closeDialogs();
    toast("Sesión cerrada. Tu carro sigue guardado en tu cuenta.");
  });
  async function updateCartCount() {
    if (!session || session.usuario.rol !== "ESPECTADOR") return;
    try {
      cartItems = list(await api("carro-tickets/"));
      $("#cart-count").textContent = String(
        cartItems.reduce((total, item) => total + item.cantidad, 0),
      );
    } catch (error) {
      toast(error.message);
    }
  }
  function startDrawer(title, eyebrow) {
    $("#drawer-title").textContent = title;
    $("#drawer-eyebrow").textContent = eyebrow;
    $("#drawer-content").innerHTML =
      '<p class="loading">Un momento, estamos preparando todo…</p>';
    showDialog("#drawer-dialog");
  }
  function drawerEmpty(title, text) {
    return `<div class="drawer-empty">${icon("ticket")}<h3>${escape(title)}</h3><p>${escape(text)}</p><button class="button lime" type="button" data-explore>Explorar eventos ${icon("arrow")}</button></div>`;
  }
  async function openCart() {
    if (!requireSpectator(openCart)) return;
    startDrawer("Mi carro", "UN PASO MÁS CERCA");
    try {
      cartItems = list(await api("carro-tickets/"));
      $("#cart-count").textContent = String(
        cartItems.reduce((total, item) => total + item.cantidad, 0),
      );
      if (!cartItems.length) {
        $("#drawer-content").innerHTML = drawerEmpty(
          "Tu próximo plan te espera.",
          "Todavía no tienes entradas en tu carro.",
        );
        return;
      }
      const total = cartItems.reduce(
        (sum, item) => sum + Number(item.precio_unitario) * item.cantidad,
        0,
      );
      $("#drawer-content").innerHTML =
        `${cartItems.map((item) => `<article class="cart-item"><div class="cart-item-icon">${icon("ticket")}</div><div class="cart-item-info"><h3>${escape(item.evento_nombre)}</h3><p>${escape(item.sector_nombre)}${item.asientos_etiquetas?.length ? ` · ${escape(item.asientos_etiquetas.join(", "))}` : ""} · ${item.cantidad} ${item.cantidad === 1 ? "entrada" : "entradas"}</p><div class="cart-item-bottom"><strong>${money(Number(item.precio_unitario) * item.cantidad)}</strong><button type="button" class="remove-item" data-remove="${item.id}">Quitar</button></div></div></article>`).join("")}<div class="cart-summary"><span>Total de tu carro</span><strong>${money(total)}</strong></div><div class="notice">Las entradas aún no están reservadas. Confirmaremos la disponibilidad y el precio al comprar.</div>${paymentEnvironment === "integration" ? '<details class="webpay-details"><summary>Webpay · Datos para el entorno de integración</summary><p>Tarjeta Visa: 4051885600446623 · CVV: 123 · Vencimiento: una fecha futura.<br>Autenticación bancaria: RUT 11111111-1 y clave 123.</p></details>' : ""}<form id="checkout-form"><label class="payment-label"><input type="checkbox" required>Revisé el evento, el sector y la cantidad de entradas que voy a comprar.</label><p id="checkout-error" class="form-error" role="alert"></p><button class="button lime full" type="submit">Pagar con Webpay ${icon("arrow")}</button></form>`;
      $("#checkout-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const submit = $('button[type="submit"]', e.currentTarget);
        submit.disabled = true;
        try {
          submit.textContent = "Conectando con Webpay…";
          const payment = await api("compras/pagar/", { method: "POST" });
          const destination = new URL(payment.url);
          const host =
            payment.ambiente === "production"
              ? "webpay3g.transbank.cl"
              : "webpay3gint.transbank.cl";
          if (
            destination.protocol !== "https:" ||
            destination.host !== host ||
            !payment.token
          )
            throw new Error("No pudimos abrir la sesión segura de Webpay.");
          const redirect = document.createElement("form");
          redirect.method = "POST";
          redirect.action = destination.href;
          const token = document.createElement("input");
          token.type = "hidden";
          token.name = "token_ws";
          token.value = payment.token;
          redirect.append(token);
          document.body.append(redirect);
          redirect.submit();
        } catch (error) {
          $("#checkout-error").textContent = error.message;
          submit.textContent = "Reintentar con Webpay";
          submit.disabled = false;
        }
      });
    } catch (error) {
      $("#drawer-content").innerHTML =
        `<div class="error-box">${escape(error.message)}</div>`;
    }
  }
  async function refreshStock() {
    await Promise.all(
      events.map(async (event) => {
        try {
          event.sectores = list(
            await api(`eventos/${event.id}/sectores/`, {
              authenticated: false,
            }),
          );
        } catch {
          /* El evento puede haber sido desactivado. */
        }
      }),
    );
    renderEvents();
  }
  async function openTickets() {
    if (!requireSpectator(openTickets)) return;
    startDrawer("Mis entradas", "TUS PRÓXIMOS RECUERDOS");
    try {
      tickets = list(await api("mis-entradas/"));
      $("#drawer-content").innerHTML = tickets.length
        ? tickets
            .map(
              (ticket) =>
                `<article class="ticket-card"><div class="ticket-top"><span>ENCORE · ENTRADA</span>${icon("ticket")}</div><div class="ticket-body"><h3>${escape(ticket.evento)}</h3><p>${escape(ticket.sector)}${ticket.asiento ? ` · Asiento ${escape(ticket.asiento)}` : ""}</p><code class="ticket-code">${escape(ticket.codigo)}</code><span class="ticket-status ${ticket.valida ? "" : "invalid"}">${!ticket.valida ? "Compra cancelada · entrada inválida" : ticket.utilizada ? "Ingreso registrado" : "Entrada disponible"}</span><button class="ticket-download" type="button" data-download="${ticket.id}">Guardar comprobante</button></div></article>`,
            )
            .join("")
        : drawerEmpty(
            "El mejor recuerdo está por venir.",
            "Tus entradas aparecerán aquí después de comprar.",
          );
    } catch (error) {
      $("#drawer-content").innerHTML =
        `<div class="error-box">${escape(error.message)}</div>`;
    }
  }
  async function openOrders() {
    if (!session) {
      pendingAction = openOrders;
      openAuth();
      return;
    }
    const organizer = session.usuario.rol === "ORGANIZADOR";
    startDrawer(
      organizer ? "Mis ventas" : "Mis compras",
      organizer ? "LA MÚSICA TAMBIÉN SE ORGANIZA" : "TU HISTORIA EN ENCORE",
    );
    try {
      const orders = list(await api("compras/"));
      $("#drawer-content").innerHTML = orders.length
        ? orders
            .map(
              (order) =>
                `<article class="order-card"><header><strong>Compra #${order.id}</strong><span class="order-status">${escape(order.estado)}</span></header><p>${date(order.creada, { day: "numeric", month: "long", year: "numeric" })}</p><p>${order.detalles.map((detail) => `${detail.cantidad} ${detail.cantidad === 1 ? "entrada" : "entradas"} · ${escape(detail.evento || detail.entradas[0]?.evento || "Evento")}`).join("<br>")}</p><strong>${money(order.total)}</strong>${organizer && order.estado === "PAGADO" ? `<div class="order-actions"><button type="button" data-order="${order.id}" data-status="ENTREGADO">Marcar ingreso</button><button type="button" data-order="${order.id}" data-status="CANCELADO">Cancelar compra</button></div>` : ""}</article>`,
            )
            .join("")
        : drawerEmpty(
            organizer
              ? "Tus ventas aparecerán aquí."
              : "Tu primera compra te espera.",
            organizer
              ? "Cuando un espectador compre entradas de tus eventos, podrás gestionar su compra."
              : "Encuentra un concierto y vive la música de cerca.",
          );
      if (!organizer && orders.some((order) => order.estado === "PENDIENTE"))
        $("#drawer-content").insertAdjacentHTML(
          "afterbegin",
          '<button class="button outline full" type="button" data-reconcile>Consultar pago pendiente en Webpay</button>',
        );
    } catch (error) {
      $("#drawer-content").innerHTML =
        `<div class="error-box">${escape(error.message)}</div>`;
    }
  }
  // Panel del organizador: la API vuelve a comprobar rol y propiedad en cada acción.
  const categoryOptions = JSON.parse($("#category-data").textContent);
  let organizationEvents = [],
    organizationVenues = [],
    sectorDraft = 0;
  function organizerAllowed() {
    if (!session) {
      pendingAction = openOrganizer;
      openAuth();
      $("#auth-title").textContent = "Acceso de organizadores";
      $("#auth-description").textContent =
        "Entra con tu cuenta de organización para gestionar tus eventos. Las cuentas se habilitan con el administrador.";
      $(".auth-switch").hidden = true;
      return false;
    }
    if (session.usuario.rol !== "ORGANIZADOR") {
      toast(
        "Tu cuenta es de espectador. El administrador debe habilitar una cuenta de organizador para gestionar eventos.",
      );
      return false;
    }
    return true;
  }
  async function openOrganizer(view = "events", eventId = null) {
    if (!organizerAllowed()) return;
    showDialog("#organizer-dialog");
    const content = $("#organizer-content");
    content.innerHTML =
      '<p class="org-loading" role="status">Preparando tu espacio…</p>';
    all("[data-org-view]").forEach((b) =>
      b.classList.toggle("active", b.dataset.orgView === view),
    );
    if (view === "sales") {
      await openOrders();
      return;
    }
    try {
      [organizationEvents, organizationVenues] = await Promise.all([
        api("eventos/mis-eventos/").then(list),
        api("recintos/").then(list),
      ]);
      if (view === "venues") {
        renderOrganizerVenues();
        return;
      }
      if (view === "new-event" || view === "edit") {
        renderOrganizerEventForm(eventId);
        return;
      }
      const active = organizationEvents.filter((e) => e.activo).length;
      content.innerHTML = `<div class="org-overview"><div><strong>${organizationEvents.length}</strong><span>Eventos en tu cuenta</span></div><div><strong>${active}</strong><span>En cartelera</span></div><button class="button lime" type="button" data-org-view="new-event">+ Crear evento</button></div><div class="org-event-list">${organizationEvents.length ? organizationEvents.map((event) => `<article class="org-event-card"><img src="${escape(imageURL(event.imagen_url) || fallbackImage)}" alt="${escape(event.artista)}" referrerpolicy="no-referrer"><div><span class="org-status ${event.activo ? "" : "paused"}">${event.activo ? "Publicado" : "Pausado"}</span><h3>${escape(event.nombre)}</h3><p>${escape(event.artista)} · ${date(event.fecha_hora, { day: "numeric", month: "long", year: "numeric" })}</p><p>${escape(organizationVenues.find((r) => r.id === event.recinto)?.nombre || "")} · ${event.sectores.length} sectores</p><div class="org-actions"><button type="button" data-org-edit="${event.id}">Editar evento</button><button type="button" data-org-sector="${event.id}">Añadir sector</button><button type="button" data-org-toggle="${event.id}" data-active="${event.activo ? "0" : "1"}">${event.activo ? "Pausar" : "Publicar"}</button>${event.activo ? `<button type="button" class="org-danger" data-org-delete="${event.id}">Retirar de cartelera</button>` : ""}</div></div></article>`).join("") : '<div class="org-empty"><h3>Tu primer show empieza aquí.</h3><p>Crea un recinto y registra tu evento con sus sectores, precios y asientos.</p></div>'}</div>`;
    } catch (error) {
      content.innerHTML = `<p class="error-box" role="alert">${escape(error.message)}</p><button type="button" class="button outline" data-org-view="events">Volver a intentar</button>`;
    }
  }
  function renderOrganizerVenues() {
    $("#organizer-content").innerHTML =
      `<div class="org-columns"><section><span class="eyebrow muted">EL LUGAR DEL SHOW</span><h3>Registrar un recinto</h3><form id="org-venue-form" class="org-form"><label>Nombre<input name="nombre" required maxlength="150" placeholder="Nombre del recinto"></label><label>Ciudad<input name="ciudad" required maxlength="100" placeholder="Ej: Concepción"></label><label>Dirección<input name="direccion" required maxlength="250" placeholder="Calle y número"></label><p class="form-error" role="alert"></p><button type="submit" class="button lime">Guardar recinto</button></form></section><section><span class="eyebrow muted">RECINTOS DISPONIBLES</span><h3>Encuentra tu escenario</h3><div class="org-venues">${organizationVenues.map((r) => `<article><strong>${escape(r.nombre)}</strong><p>${escape(r.ciudad)} · ${escape(r.direccion)}</p></article>`).join("") || "<p>Todavía no hay recintos registrados.</p>"}</div></section></div>`;
    $("#org-venue-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.currentTarget,
        button = $('button[type="submit"]', form);
      button.disabled = true;
      try {
        const body = Object.fromEntries(new FormData(form));
        await api("recintos/", { method: "POST", body });
        await openOrganizer("venues");
        toast("Recinto registrado. Ya puedes usarlo en tus eventos.");
      } catch (error) {
        $(".form-error", form).textContent = error.message;
        button.disabled = false;
      }
    });
  }
  function addSectorRow(values = {}) {
    const key = ++sectorDraft;
    $("#org-sector-rows").insertAdjacentHTML(
      "beforeend",
      `<div class="org-sector-row" data-sector-row><label>Sector<input name="sector_${key}" data-field="nombre" required maxlength="100" value="${escape(values.nombre || "")}" placeholder="Ej: VIP"></label><label>Precio CLP<input type="number" data-field="precio" required min="1" step="1" value="${values.precio || ""}" placeholder="35000"></label><label>Entradas<input type="number" data-field="stock" required min="1" max="5000" step="1" value="${values.stock || ""}" placeholder="100"></label><button type="button" class="org-remove-sector" data-org-remove-sector aria-label="Quitar sector">×</button></div>`,
    );
  }
  function renderOrganizerEventForm(eventId) {
    const event = organizationEvents.find((e) => e.id === Number(eventId));
    if (!organizationVenues.length) {
      $("#organizer-content").innerHTML =
        '<div class="org-empty"><h3>Primero, el lugar.</h3><p>Registra un recinto antes de crear tu evento.</p><button type="button" class="button lime" data-org-view="venues">Registrar recinto</button></div>';
      return;
    }
    const localDate = event
      ? new Intl.DateTimeFormat("sv-SE", {
          timeZone: "America/Santiago",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        })
          .format(new Date(event.fecha_hora))
          .replace(" ", "T")
      : "";
    const isPast = event && new Date(event.fecha_hora) <= new Date();
    $("#organizer-content").innerHTML =
      `<div class="org-form-heading"><h3>${event ? "Editar tu evento" : "Vamos a crear un gran show."}</h3><p>${event ? "Actualiza la información de tu concierto." : "Los asientos se generan automáticamente al guardar tus sectores."}</p></div><form id="org-event-form" class="org-form"><div class="org-fields"><label>Nombre del evento<input name="nombre" required maxlength="200" value="${escape(event?.nombre || "")}" placeholder="Nombre del show"></label><label>Artista o banda<input name="artista" required maxlength="150" value="${escape(event?.artista || "")}" placeholder="Quién sube al escenario"></label><label>Fecha y hora (Chile)<input type="datetime-local" name="fecha_hora" required value="${escape(localDate)}" ${isPast ? "disabled" : ""}></label><label>Recinto<select name="recinto" required>${organizationVenues.map((r) => `<option value="${r.id}" ${r.id === event?.recinto ? "selected" : ""}>${escape(r.nombre)} · ${escape(r.ciudad)}</option>`).join("")}</select></label><label>Categoría<select name="categoria">${categoryOptions.map(([code, label]) => `<option value="${code}" ${code === event?.categoria ? "selected" : ""}>${escape(label)}</option>`).join("")}</select></label><label>Imagen de portada (opcional)<input type="url" name="imagen_url" maxlength="1000" value="${escape(event?.imagen_url || "")}" placeholder="https://…"></label></div><label>Descripción<textarea name="descripcion" rows="3" maxlength="5000" placeholder="Cuéntanos cómo será esta experiencia">${escape(event?.descripcion || "")}</textarea></label>${event ? `<div class="org-current-sectors"><h4>Localidades actuales</h4>${event.sectores.map((s) => `<p>${escape(s.nombre)} · ${money(s.precio)} · ${s.stock} entradas disponibles</p>`).join("")}</div>` : '<section class="org-sector-section"><div class="org-section-heading"><h4>Sectores y localidades</h4><button type="button" class="text-link" data-org-add-sector>+ Añadir sector</button></div><div id="org-sector-rows"></div><small>Máximo 10 sectores. Hasta 5.000 sillas por sector.</small></section>'}<p class="form-error" role="alert"></p><div class="org-form-actions"><button type="submit" class="button lime">${event ? "Guardar cambios" : "Publicar evento"}</button><button type="button" class="button outline" data-org-view="events">Volver a mis eventos</button></div></form>`;
    if (!event) {
      addSectorRow({ nombre: "Cancha general", precio: 35000, stock: 100 });
      addSectorRow({ nombre: "Tribuna", precio: 55000, stock: 80 });
      addSectorRow({ nombre: "VIP", precio: 85000, stock: 40 });
    }
    $("#org-event-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.currentTarget,
        button = $('button[type="submit"]', form);
      button.disabled = true;
      $(".form-error", form).textContent = "";
      try {
        const body = Object.fromEntries(new FormData(form));
        body.recinto = Number(body.recinto);
        // Enviar la zona de Santiago explícita: no depende de la zona del dispositivo.
        if (body.fecha_hora) {
          const instant = chileanDateToISO(body.fecha_hora);
          if (new Date(instant) <= new Date())
            throw new Error("Elige una fecha futura.");
          body.fecha_hora = instant;
        }
        if (body.imagen_url && !body.imagen_url.startsWith("https://"))
          throw new Error("La imagen de portada debe usar HTTPS.");
        if (!event) {
          body.sectores = all("[data-sector-row]", form).map((row) => ({
            nombre: $('[data-field="nombre"]', row).value.trim(),
            precio: $('[data-field="precio"]', row).value,
            stock: Number($('[data-field="stock"]', row).value),
          }));
          if (!body.sectores.length)
            throw new Error("Añade al menos un sector.");
        }
        Object.keys(body)
          .filter((k) => k.startsWith("sector_"))
          .forEach((k) => delete body[k]);
        await api(event ? `eventos/${event.id}/` : "eventos/crear-completo/", {
          method: event ? "PATCH" : "POST",
          body,
        });
        await refreshCatalogue();
        await openOrganizer();
        toast(
          event ? "Cambios guardados." : "Evento publicado con sus asientos.",
        );
      } catch (error) {
        $(".form-error", form).textContent = error.message;
        button.disabled = false;
      }
    });
  }
  function chileanDateToISO(value) {
    const target = new Date(value + "Z");
    let instant = new Date(target);
    for (let i = 0; i < 3; i++) {
      const parts = new Intl.DateTimeFormat("sv-SE", {
        timeZone: "America/Santiago",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(instant);
      const represented = new Date(parts.replace(" ", "T") + "Z");
      instant = new Date(
        instant.getTime() + target.getTime() - represented.getTime(),
      );
    }
    const actual = new Intl.DateTimeFormat("sv-SE", {
      timeZone: "America/Santiago",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
      .format(instant)
      .replace(" ", "T");
    if (actual !== value)
      throw new Error(
        "Esta hora no existe por el cambio de horario. Elige otra hora.",
      );
    return instant.toISOString();
  }
  async function refreshCatalogue() {
    const [catalogue, venues] = await Promise.all([
      api("eventos/", { authenticated: false }).then(list),
      api("recintos/", { authenticated: false }).then(list),
    ]);
    const labels = new Map(categoryOptions);
    events.splice(
      0,
      events.length,
      ...catalogue
        .filter((e) => e.activo && new Date(e.fecha_hora) > new Date())
        .map((e) => ({
          id: e.id,
          nombre: e.nombre,
          artista: e.artista,
          descripcion: e.descripcion,
          fecha: e.fecha_hora,
          recinto: venues.find((r) => r.id === e.recinto)?.nombre || "",
          ciudad: venues.find((r) => r.id === e.recinto)?.ciudad || "",
          imagen: e.imagen_url,
          demo: e.es_demo,
          sectores: e.sectores,
          categoria: labels.get(e.categoria),
        })),
    );
    const current = $("#city-filter").value;
    $("#city-filter").innerHTML =
      '<option value="">Todas las ciudades</option>' +
      [...new Set(events.map((e) => e.ciudad))]
        .sort()
        .map((c) => `<option value="${escape(c)}">${escape(c)}</option>`)
        .join("");
    $("#city-filter").value = [...$("#city-filter").options].some(
      (o) => o.value === current,
    )
      ? current
      : "";
    renderEvents();
  }
  function renderAdditionalSector(id) {
    const event = organizationEvents.find((e) => e.id === Number(id));
    if (!event) return;
    $("#organizer-content").innerHTML =
      `<div class="org-form-heading"><h3>Añadir localidad</h3><p>${escape(event.nombre)}</p></div><form id="org-extra-sector" class="org-form"><div id="org-sector-rows"></div><p class="form-error" role="alert"></p><button type="submit" class="button lime">Guardar sector y generar asientos</button><button type="button" class="button outline" data-org-view="events">Volver</button></form>`;
    addSectorRow();
    $(".org-remove-sector").hidden = true;
    $("#org-extra-sector").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.currentTarget,
        b = $('button[type="submit"]', f);
      b.disabled = true;
      try {
        await api("sectores/", {
          method: "POST",
          body: {
            evento: event.id,
            nombre: $('[data-field="nombre"]', f).value.trim(),
            precio: $('[data-field="precio"]', f).value,
            stock: Number($('[data-field="stock"]', f).value),
          },
        });
        await refreshCatalogue();
        await openOrganizer();
        toast("Localidad lista para vender entradas.");
      } catch (error) {
        $(".form-error", f).textContent = error.message;
        b.disabled = false;
      }
    });
  }
  $("#organizer-access").addEventListener("click", () => openOrganizer());
  $("#my-events").addEventListener("click", () => openOrganizer());
  $("#organizer-dialog").addEventListener("click", async (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    if (button.dataset.orgView) await openOrganizer(button.dataset.orgView);
    if (button.dataset.orgEdit)
      await openOrganizer("edit", button.dataset.orgEdit);
    if (button.dataset.orgSector)
      renderAdditionalSector(button.dataset.orgSector);
    if (button.hasAttribute("data-org-add-sector")) {
      if (all("[data-sector-row]").length < 10) addSectorRow();
      else toast("Puedes registrar hasta 10 sectores.");
    }
    if (button.hasAttribute("data-org-remove-sector")) {
      if (all("[data-sector-row]").length > 1)
        button.closest("[data-sector-row]").remove();
      else toast("El evento necesita al menos un sector.");
    }
    if (button.dataset.orgToggle || button.dataset.orgDelete) {
      const id = button.dataset.orgToggle || button.dataset.orgDelete;
      if (
        button.dataset.orgDelete &&
        !window.confirm(
          "¿Retirar este evento de la cartelera? Las compras y entradas se conservarán.",
        )
      )
        return;
      button.disabled = true;
      try {
        await api(`eventos/${id}/`, {
          method: button.dataset.orgDelete ? "DELETE" : "PATCH",
          body: button.dataset.orgDelete
            ? undefined
            : { activo: button.dataset.active === "1" },
        });
        await refreshCatalogue();
        await openOrganizer();
        toast(
          button.dataset.orgDelete
            ? "Evento retirado de la cartelera."
            : "Cartelera actualizada.",
        );
      } catch (error) {
        toast(error.message);
        button.disabled = false;
      }
    }
  });

  $("#cart-button").addEventListener("click", openCart);
  $("#my-tickets").addEventListener("click", openTickets);
  $("#footer-tickets").addEventListener("click", openTickets);
  $("#my-orders").addEventListener("click", openOrders);
  $("#help-button").addEventListener("click", () => showDialog("#help-dialog"));

  // Delegación de acciones para tarjetas y paneles que se actualizan dinámicamente.
  document.addEventListener("click", async (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    if (button.hasAttribute("data-close")) {
      button.closest("dialog").close();
      return;
    }
    if (button.dataset.category) setCategory(button.dataset.category);
    if (button.dataset.filterLink) {
      setCategory(button.dataset.filterLink);
      $("#cartelera").scrollIntoView({ behavior: "smooth" });
    }
    if (button.dataset.event) await openEvent(button.dataset.event);
    if (button.hasAttribute("data-explore")) {
      closeDialogs();
      $("#cartelera").scrollIntoView({ behavior: "smooth" });
    }
    if (button.hasAttribute("data-show-tickets")) await openTickets();
    if (button.dataset.step) {
      const input = $("#ticket-quantity");
      input.value = Math.max(
        1,
        Math.min(
          Number(input.max),
          Number(input.value) + Number(button.dataset.step),
        ),
      );
      input.dispatchEvent(new Event("input"));
    }
    if (button.dataset.remove) {
      button.disabled = true;
      try {
        await api(`carro-tickets/${button.dataset.remove}/`, {
          method: "DELETE",
        });
        await openCart();
      } catch (error) {
        toast(error.message);
        button.disabled = false;
      }
    }
    if (button.dataset.order) {
      const cancel = button.dataset.status === "CANCELADO";
      if (
        !window.confirm(
          cancel
            ? "¿Cancelar esta compra y devolver las entradas disponibles?"
            : "¿Marcar todas las entradas de esta compra como utilizadas?",
        )
      )
        return;
      button.disabled = true;
      try {
        await api(`compras/${button.dataset.order}/estado/`, {
          method: "PATCH",
          body: { estado: button.dataset.status },
        });
        await openOrders();
        await refreshStock();
        toast(
          cancel
            ? "Compra cancelada. Stock restituido."
            : "Ingreso registrado.",
        );
      } catch (error) {
        toast(error.message);
        button.disabled = false;
      }
    }
    if (button.hasAttribute("data-reconcile")) {
      button.disabled = true;
      try {
        await api("compras/conciliar/", { method: "POST" });
        await openOrders();
        await updateCartCount();
      } catch (error) {
        toast(error.message);
        button.disabled = false;
      }
    }
    if (button.dataset.download) {
      const ticket = tickets.find(
        (item) => item.id === Number(button.dataset.download),
      );
      const text = `ENCORE · COMPROBANTE DE ENTRADA\n\nEvento: ${ticket.evento}\nSector: ${ticket.sector}\nAsiento: ${ticket.asiento || "Sin numeración"}\nCódigo: ${ticket.codigo}\nEstado: ${!ticket.valida ? "Cancelada" : ticket.utilizada ? "Utilizada" : "Disponible"}\n\n${ticket.es_demo ? "Comprobante emitido en el entorno de integración. No acredita un cobro comercial." : "Conserva este código y consulta las condiciones de ingreso del organizador."}`;
      const url = URL.createObjectURL(
        new Blob([text], { type: "text/plain;charset=utf-8" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `encore-entrada-${ticket.id}.txt`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  });
  all("dialog").forEach((dialog) =>
    dialog.addEventListener("click", (e) => {
      if (e.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      )
        dialog.close();
    }),
  );
  const paymentMessages = JSON.parse($("#payment-result-data").textContent);
  if (paymentMessages.length) {
    const message = paymentMessages.join(" "),
      approved = message.includes("¡Pago aprobado!");
    $("#payment-title").textContent = approved
      ? "¡Tu compra está pagada!"
      : "Resultado de tu pago";
    $("#payment-message").textContent = message;
    $("#payment-tickets").hidden = !approved;
    $(".payment-mark").textContent = approved ? "✓" : "→";
    showDialog("#payment-dialog");
  }
  updateAccount();
  renderEvents();
  updateCartCount();
  if (new URLSearchParams(location.search).has("mis-compras")) {
    history.replaceState(null, "", "/");
    openOrders();
  }
})();
