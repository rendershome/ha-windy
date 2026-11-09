// Dashboard cards for the Windy integration.
const BASE = "/windy_static";

class WindyMapCard extends HTMLElement {
  static getStubConfig() {
    return { overlay: "wind", zoom: 7 };
  }

  setConfig(config) {
    this._config = { overlay: "wind", zoom: 7, height: 450, ...config };
    this._started = false;
    this.innerHTML = "";
  }

  getCardSize() {
    return Math.ceil(this._config.height / 50);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._started && this._config) {
      this._started = true;
      this._start();
    }
  }

  async _start() {
    const card = document.createElement("ha-card");
    if (this._config.title) card.header = this._config.title;
    const body = document.createElement("div");
    body.style.cssText = `position:relative;height:${Number(this._config.height)}px;overflow:hidden;border-radius:inherit`;
    card.append(body);
    this.replaceChildren(card);

    let entries;
    try {
      entries = await this._hass.callWS({ type: "windy/map_config" });
    } catch (err) {
      this._message(body, "Couldn't reach the Windy integration. Restart Home Assistant after installing it.");
      return;
    }
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
    const onMessage = (event) => {
      if (event.source !== frame.contentWindow || event.origin !== location.origin) return;
      if (event.data?.type !== "windy-ready") return;
      window.removeEventListener("message", onMessage);
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
    window.addEventListener("message", onMessage);
    body.append(frame);
  }

  _message(parent, text) {
    const note = document.createElement("div");
    note.style.padding = "16px";
    note.textContent = text;
    parent.replaceChildren(note);
  }
}

class WindyWebcamCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("camera.") && hass.states[id].attributes.windy_url,
    );
    return { entity: entity ?? "" };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Choose a Windy webcam camera entity");
    this._config = config;
    this._image = undefined;
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
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
