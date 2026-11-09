// Dashboard cards for the Windy integration.
const BASE = "/windy_static";
const REDRAW_DELAY_MS = 500;

const options = (entries) =>
  Object.entries(entries).map(([value, label]) => ({ value, label }));

const OVERLAYS = options({
  wind: "Wind",
  gust: "Wind gusts",
  rain: "Rain and thunder",
  rainAccu: "Rain accumulation",
  snowAccu: "New snow",
  snowcover: "Snow depth",
  ptype: "Precipitation type",
  thunder: "Thunderstorms",
  temp: "Temperature",
  dewpoint: "Dew point",
  rh: "Humidity",
  deg0: "Freezing level",
  pressure: "Pressure",
  clouds: "Clouds",
  lclouds: "Low clouds",
  mclouds: "Medium clouds",
  hclouds: "High clouds",
  cloudtop: "Cloud tops",
  cbase: "Cloud base",
  visibility: "Visibility",
  fog: "Fog",
  cape: "CAPE index",
  radar: "Weather radar",
  satellite: "Satellite",
  waves: "Waves",
  swell1: "Swell",
  wwaves: "Wind waves",
  currents: "Currents",
  sst: "Sea temperature",
  airQ: "Air quality",
  pm2p5: "PM2.5",
  no2: "Nitrogen dioxide",
  gtco3: "Ozone",
  aod550: "Aerosols",
  cosc: "Carbon monoxide",
  dustsm: "Dust",
  fires: "Fires",
});

const PRODUCTS = options({
  gfs: "GFS (global)",
  ecmwf: "ECMWF (global)",
  icon: "ICON (global)",
  iconEu: "ICON-EU (Europe)",
  iconD2: "ICON-D2 (Germany)",
  arome: "AROME (France and nearby)",
  namConus: "NAM (contiguous USA)",
  namAlaska: "NAM (Alaska)",
  namHawaii: "NAM (Hawaii)",
  hrrrConus: "HRRR (contiguous USA)",
  hrrrAlaska: "HRRR (Alaska)",
});

const LEVELS = options({
  surface: "Surface",
  "100m": "100 m",
  "975h": "975 hPa",
  "950h": "950 hPa",
  "925h": "925 hPa",
  "900h": "900 hPa",
  "850h": "850 hPa",
  "800h": "800 hPa",
  "700h": "700 hPa",
  "600h": "600 hPa",
  "500h": "500 hPa",
  "400h": "400 hPa",
  "300h": "300 hPa",
  "250h": "250 hPa",
  "200h": "200 hPa",
  "150h": "150 hPa",
});

const MAP_LABELS = {
  title: "Title",
  location: "Location",
  overlay: "Map layer",
  zoom: "Zoom",
  height: "Height",
  product: "Forecast model",
  level: "Altitude",
  latitude: "Center latitude",
  longitude: "Center longitude",
};

const MAP_HELPERS = {
  overlay: "Some layers need a Professional Windy key. The map says so if yours doesn't include the one you choose.",
  product: "Leave blank to use Windy's default.",
  level: "Leave blank for the surface. Not every layer has altitude levels.",
  latitude: "Leave blank to center on the Windy location.",
  longitude: "Leave blank to center on the Windy location.",
};

const select = (name, choices, required = false) => ({
  name,
  required,
  selector: { select: { mode: "dropdown", options: choices } },
});

const dropEmpty = (config) =>
  Object.fromEntries(
    Object.entries(config).filter(([, value]) => value !== undefined && value !== null && value !== ""),
  );

class WindyMapCard extends HTMLElement {
  static getStubConfig() {
    return { overlay: "wind", zoom: 7, height: 450 };
  }

  static async getConfigForm() {
    // A location menu is only useful with more than one location.
    let locations = [];
    try {
      const hass = document.querySelector("home-assistant")?.hass;
      const entries = await hass?.callWS({ type: "windy/map_config" });
      locations = (entries ?? []).map((entry) => entry.title);
    } catch (err) {
      locations = [];
    }
    const locationField =
      locations.length > 1
        ? [select("location", locations.map((title) => ({ value: title, label: title })))]
        : [];
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        ...locationField,
        select("overlay", OVERLAYS, true),
        { name: "zoom", selector: { number: { min: 3, max: 11, step: 1, mode: "slider" } } },
        {
          name: "height",
          selector: { number: { min: 200, max: 1000, step: 10, mode: "box", unit_of_measurement: "px" } },
        },
        {
          type: "expandable",
          name: "",
          flatten: true,
          title: "Advanced",
          schema: [
            select("product", PRODUCTS),
            select("level", LEVELS),
            { name: "latitude", selector: { number: { min: -90, max: 90, step: "any", mode: "box" } } },
            { name: "longitude", selector: { number: { min: -180, max: 180, step: "any", mode: "box" } } },
          ],
        },
      ],
      computeLabel: (schema) => MAP_LABELS[schema.name],
      computeHelper: (schema) => MAP_HELPERS[schema.name],
    };
  }

  setConfig(config) {
    const next = { overlay: "wind", zoom: 7, height: 450, ...dropEmpty(config) };
    if (JSON.stringify(next) === JSON.stringify(this._config)) return;
    this._config = next;
    // Redraw after a pause, so dragging a slider doesn't reload the map each step.
    clearTimeout(this._redraw);
    if (this._started && this._hass) {
      this._redraw = setTimeout(() => this._start(), REDRAW_DELAY_MS);
    }
  }

  getCardSize() {
    return Math.ceil(Number(this._config.height) / 50);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._started && this._config) {
      this._started = true;
      this._start();
    }
  }

  async _start() {
    const run = (this._run = (this._run ?? 0) + 1);
    if (this._onMessage) window.removeEventListener("message", this._onMessage);
    this._onMessage = undefined;

    const card = document.createElement("ha-card");
    if (this._config.title) card.header = this._config.title;
    const body = document.createElement("div");
    body.style.cssText = `position:relative;height:${Number(this._config.height) || 450}px;overflow:hidden;border-radius:inherit`;
    card.append(body);
    this.replaceChildren(card);

    let entries;
    try {
      entries = await this._hass.callWS({ type: "windy/map_config" });
    } catch (err) {
      if (run === this._run) {
        this._message(body, "Couldn't reach the Windy integration. Restart Home Assistant after installing it.");
      }
      return;
    }
    if (run !== this._run) return; // The settings changed while waiting.
    const wanted = this._config.location;
    const entry = wanted ? entries.find((e) => e.title === wanted) : entries[0];
    if (!entry) {
      this._message(
        body,
        wanted
          ? `No Windy location named "${wanted}" has a Map Forecast key.`
          : "Add a Map Forecast key to a Windy location to show this map.",
      );
      return;
    }

    // Windy's library needs a plain document and only allows one map per page,
    // so it runs in a same-origin frame. Its key is sent by message, not URL.
    const frame = document.createElement("iframe");
    frame.src = `${BASE}/map.html`;
    frame.title = "Windy map";
    frame.style.cssText = "border:0;width:100%;height:100%;display:block";
    // Moving a card in the page reloads its frame, and the reloaded frame asks
    // for its settings again, so this keeps listening while the card is attached.
    this._onMessage = (event) => {
      if (event.source !== frame.contentWindow || event.origin !== location.origin) return;
      if (event.data?.type !== "windy-ready") return;
      const { overlay, level, product, zoom, latitude, longitude } = this._config;
      frame.contentWindow.postMessage(
        {
          type: "windy-init",
          key: entry.key,
          lat: latitude ?? entry.latitude,
          lon: longitude ?? entry.longitude,
          marker: { lat: entry.latitude, lon: entry.longitude },
          zoom,
          overlay,
          level,
          product,
        },
        location.origin,
      );
    };
    if (this.isConnected) window.addEventListener("message", this._onMessage);
    body.append(frame);
  }

  connectedCallback() {
    if (this._onMessage) window.addEventListener("message", this._onMessage);
  }

  disconnectedCallback() {
    if (this._onMessage) window.removeEventListener("message", this._onMessage);
  }

  _message(parent, text) {
    const note = document.createElement("div");
    note.style.padding = "16px";
    note.textContent = text;
    parent.replaceChildren(note);
  }
}

const WEBCAM_LABELS = { entity: "Webcam", title: "Title" };
const WEBCAM_HELPERS = { title: "Leave blank to use the webcam's name." };

class WindyWebcamCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("camera.") && hass.states[id].attributes.windy_url,
    );
    return { entity: entity ?? "" };
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { filter: [{ integration: "windy", domain: "camera" }] } },
        },
        { name: "title", selector: { text: {} } },
      ],
      computeLabel: (schema) => WEBCAM_LABELS[schema.name],
      computeHelper: (schema) => WEBCAM_HELPERS[schema.name],
    };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Choose a Windy webcam camera entity");
    this._config = dropEmpty(config);
    this._image = undefined;
    // Show the change right away instead of waiting for the next state update.
    if (this._hass) this.hass = this._hass;
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._config.entity];
    if (!this._image) this._build();
    if (!state) {
      this._title.textContent = `${this._config.entity} not found`;
      return;
    }
    const attrs = state.attributes;
    this._title.textContent = this._config.title ?? attrs.friendly_name ?? "";
    if (attrs.windy_url) this._link.href = attrs.windy_url;
    const picture = attrs.entity_picture;
    if (picture) {
      // Windy refreshes the image URL, so reload when the entity updates.
      const url = `${picture}&updated=${encodeURIComponent(state.last_updated)}`;
      if (this._image.getAttribute("src") !== url) this._image.src = url;
    }
  }

  // Windy's terms ask for the image to link to the webcam's page, stay at its
  // original size or smaller, and show a Windy.com credit in the corner.
  _build() {
    const card = document.createElement("ha-card");
    card.innerHTML = `
      <div style="padding:12px 16px 4px;font-weight:500" class="title"></div>
      <div style="position:relative;text-align:center;line-height:0">
        <a class="link" target="_blank" rel="noopener noreferrer">
          <img style="max-width:100%;height:auto;display:inline-block" alt="" />
        </a>
        <div style="position:absolute;right:0;bottom:0;padding:2px 6px;font-size:11px;line-height:16px;background:rgba(0,0,0,.55);color:#fff">
          Webcams provided by
          <a href="https://www.windy.com/" target="_blank" rel="noopener noreferrer" style="color:inherit">windy.com</a>
          &ndash;
          <a href="https://www.windy.com/webcams/add" target="_blank" rel="noopener noreferrer" style="color:inherit">add a webcam</a>
        </div>
      </div>`;
    this._title = card.querySelector(".title");
    this._link = card.querySelector(".link");
    this._image = card.querySelector("img");
    this.replaceChildren(card);
  }
}

if (!customElements.get("windy-map-card")) {
  customElements.define("windy-map-card", WindyMapCard);
}
if (!customElements.get("windy-webcam-card")) {
  customElements.define("windy-webcam-card", WindyWebcamCard);
}
window.customCards = window.customCards || [];
window.customCards.push(
  {
    type: "windy-map-card",
    name: "Windy map",
    description: "Windy's animated weather map, using your Map Forecast key.",
  },
  {
    type: "windy-webcam-card",
    name: "Windy webcam",
    description: "A Windy webcam image with the required credit and link.",
  },
);
