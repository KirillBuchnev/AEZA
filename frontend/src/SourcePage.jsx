import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { Icon } from "./Icons.jsx";
import { CardHead, PageHead } from "./Shared.jsx";
import { plural, timeLabel } from "./format.js";

const MAX_FILE_BYTES = 10 * 1024 * 1024;

const eventText = {
  model_settings_changed: "Изменены коэффициенты модели",
  source_snapshot_changed: "Загружен новый снимок данных",
};

function readJson(file) {
  return new Promise((resolve, reject) => {
    if (file.size > MAX_FILE_BYTES) {
      reject(new Error("Файл больше 10 МБ."));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        resolve(JSON.parse(reader.result));
      } catch {
        reject(new Error("Это не JSON: проверьте, что файл не обрезан."));
      }
    };
    reader.onerror = () => reject(new Error("Не удалось прочитать файл."));
    reader.readAsText(file);
  });
}

export function SourcePage({ summary, updates, onToast, version }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [metrics, setMetrics] = useState("");

  useEffect(() => {
    let active = true;
    api
      .metrics()
      .then((text) => {
        if (!active) return;
        setMetrics(
          text
            .split("\n")
            .filter((line) => line && !line.startsWith("#"))
            .join("\n"),
        );
      })
      .catch(() => active && setMetrics(""));
    return () => {
      active = false;
    };
  }, [version]);

  async function upload(file) {
    if (!file) return;
    setUploadError("");
    setUploading(true);
    try {
      const json = await readJson(file);
      const payload = Array.isArray(json) ? { customers: json } : json;
      const result = await api.uploadSnapshot(payload);
      onToast({
        kind: "success",
        message: `Снимок принят: ${result.customers_received} ${plural(result.customers_received, ["клиент", "клиента", "клиентов"])}, риск пересчитан`,
      });
    } catch (error) {
      setUploadError(error.message);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  const counts = summary?.risk_counts || {};
  const updatedAt = summary?.source_updated_at;

  return (
    <>
      <PageHead
        title="Источник данных"
        description="Аккаунты, услуги и транзакции. Новые данные пересчитывают риск сами — страницу обновлять не нужно"
      >
        <button
          className="button button-primary"
          onClick={() => input.current?.click()}
          disabled={uploading}
        >
          <Icon name="upload" size={16} />
          Загрузить снимок
        </button>
      </PageHead>

      <div className="row-split">
        <section className="card">
          <CardHead
            title="Текущий снимок"
            description={`${summary?.source_kind === "demo" ? "Демо-данные" : "Загружен через PUT /api/v1/source/snapshot"} · обновлён ${updatedAt ? new Date(updatedAt).toLocaleString("ru-RU") : "—"}`}
          />
          <div className="stats">
            <div>
              <span>Клиентов</span>
              <b className="number">{summary?.customers_total ?? "—"}</b>
            </div>
            <div>
              <span>С оценкой</span>
              <b className="number">{summary?.assessed_total ?? "—"}</b>
            </div>
            <div>
              <span>Высокий риск</span>
              <b className="number">{counts.high ?? "—"}</b>
            </div>
            <div>
              <span>Без оценки</span>
              <b className="number">{counts.unscored ?? "—"}</b>
            </div>
          </div>
        </section>

        <label
          className={`dropzone${over ? " dropzone-over" : ""}${uploadError ? " dropzone-error" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            upload(event.dataTransfer.files?.[0]);
          }}
        >
          <input
            ref={input}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(event) => upload(event.target.files?.[0])}
          />
          <span className="upload-icon">
            <Icon name="upload" size={22} />
          </span>
          <b>
            {uploading
              ? "Загружаем и пересчитываем…"
              : uploadError
                ? "Файл не подошёл"
                : "Перетащите JSON-снимок сюда"}
          </b>
          <p>
            {uploadError
              ? `${uploadError} Текущий снимок на месте, расчёты не менялись.`
              : "Или нажмите, чтобы выбрать файл. Полная замена: customers с услугами и транзакциями, суммы — в евроцентах."}
          </p>
        </label>
      </div>

      <div className="row-split">
        <section className="card">
          <CardHead
            title="Журнал обновлений"
            description="События этой сессии: что поменялось и когда панель пересчиталась"
          />
          {updates.length ? (
            <div>
              {updates.map((update) => (
                <div className="log-row" key={update.id}>
                  <time>{timeLabel(update.at).slice(0, 5)}</time>
                  <span className="dot" />
                  <div>
                    <span>{eventText[update.type] || update.type}</span>
                    <small>Рейтинг, деньги и метрики пересчитаны</small>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">
              Пока изменений не было. Поменяйте коэффициент или загрузите снимок
              — событие появится здесь сразу.
            </p>
          )}
        </section>

        <section className="dev">
          <h2 className="h2">Для интеграции</h2>
          <p>GET /metrics — те же числа, что на панели, в формате Prometheus</p>
          <pre>{metrics || "Метрики недоступны"}</pre>
          <a href="/api/v1/docs" target="_blank" rel="noreferrer">
            Swagger: /api/v1/docs →
          </a>
        </section>
      </div>
    </>
  );
}
