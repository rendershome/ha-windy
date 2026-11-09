# Windy for Home Assistant

An unofficial Home Assistant integration for [Windy.com](https://www.windy.com) APIs. It isn't affiliated with or endorsed by Windy. You need your own API keys from [api.windy.com/keys](https://api.windy.com/keys).

| Windy API | What you get |
|---|---|
| Point Forecast | A weather entity with hourly and daily forecasts, plus sensors for wind, temperature, pressure, precipitation, clouds and air quality |
| Webcams | A camera entity for each nearby webcam, or for the webcam IDs you choose |
| Map Forecast | A dashboard card with Windy's animated weather map |

The Windy Plugins API isn't used, because those plugins run inside windy.com.

All keys are optional, so you only need the ones for the features you want.

## Install

Requires Home Assistant 2026.10 or later.

1. In Home Assistant, go to **Settings → Marketplace** and add a custom repository by link: `https://github.com/rendershome/ha-windy` (type: Integration). Custom repositories need a GitHub connection.
2. Install **Windy** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Windy**.

To install manually, copy `custom_components/windy` into your `config/custom_components` folder and restart.

To add more locations, add the integration again. Keys from an existing location are filled in for you.

## Creating Windy API keys

Create a separate key for each service:

- **Project identification:** anything that identifies your use, such as `home-assistant-windy-integration`.
- **Domain restrictions:** leave blank for Point Forecast and Webcams, because those requests come from your Home Assistant server. For Map Forecast, leave it blank unless you reach Home Assistant through a domain you can list. A restriction may block access by IP address or `homeassistant.local`.

### Free test keys

- **Point Forecast:** test keys return data for **random coordinates**, so the values aren't your real weather.
- **Map Forecast:** the free version is limited and is for development only. In testing, a limited key allowed only the wind, temperature and pressure layers on the GFS model. Production use needs the Professional version.
- **Webcams:** free image links expire after 10 minutes, so keep the webcam update interval under 10 minutes.

Check [Windy's API pages](https://api.windy.com) for current terms and pricing.

## Dashboard cards

The cards are loaded automatically when the integration starts. To add one, edit a dashboard, choose **Add card → By card**, and search for **Windy**. Both cards have menus for their settings, and you can use YAML instead with **Show code editor**.

### Map

```yaml
type: custom:windy-map-card
title: Wind
overlay: wind
zoom: 7
height: 450
```

| Option | Default | Description |
|---|---|---|
| `location` | First location with a map key | Name of the Windy location to use. The menu only appears with more than one location. |
| `overlay` | `wind` | Map layer, such as `wind`, `temp` or `pressure`. Other layers, such as `rain` or `clouds`, may need a Professional key. |
| `zoom` | `7` | Zoom level |
| `height` | `450` | Card height in pixels |
| `level` | Windy's default | Altitude level, such as `surface` or `850h` |
| `product` | Windy's default | Forecast model used by the map |
| `latitude`, `longitude` | The location's | Map center |

If your key doesn't include a layer, model or altitude you choose, the map shows a notice and uses Windy's default.

The map key has to reach your browser for Windy's map to work, so any logged-in Home Assistant user can read it. It isn't stored in dashboard YAML.

### Webcam

```yaml
type: custom:windy-webcam-card
entity: camera.home_your_webcam
```

[Windy's webcam terms](https://api.windy.com/webcams/terms) ask for a Windy.com credit and a link to each webcam's page. This card includes both and doesn't stretch images. If you show a Windy camera with another card, those requirements are yours to meet. The camera's `windy_url` attribute has the link.

## Options

Open **Configure** on the integration to change the forecast model, air quality model, update intervals, webcam search radius and count, or to list specific webcam IDs.

- `gfs` is the default global model and covers about 10 days.
- `canHrdps` has higher resolution for Canada but a shorter range. It has no precipitation type, so rain or snow is estimated from temperature.
- Precipitation values for each step are estimated from Windy's rolling 3-hour totals.
- Air quality adds one more Point Forecast request per update.

To change keys, choose **Reconfigure** on the integration. If Windy rejects a key, Home Assistant asks you for a new one.

## Development

Tests use [pytest-homeassistant-custom-component](https://github.com/MatthewScholefield/pytest-homeassistant-custom-component) on Linux and a simulated Windy API:

```bash
pip install pytest-homeassistant-custom-component
pytest
```

## License

MIT. Weather data and webcam images belong to Windy and its providers, and are subject to [Windy's terms](https://api.windy.com).
