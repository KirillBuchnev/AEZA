import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { Icon } from "./Icons.jsx";
import { matchError, passwordError } from "./authRules.js";

export function PasswordDialog({ username, onClose, onDone, onExpired }) {
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const firstFieldRef = useRef(null);

  // Move focus into the dialog and give it back to the trigger when it closes.
  useEffect(() => {
    const opener = document.activeElement;
    firstFieldRef.current?.focus();
    return () => opener?.focus?.();
  }, []);

  // Closing is blocked while a save is in flight, so a failed save is never hidden.
  const requestClose = () => {
    if (!saving) onClose();
  };

  useEffect(() => {
    const closeOnEscape = (event) => {
      if (event.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  });

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  async function save(event) {
    event.preventDefault();
    setError("");
    const problem =
      (form.current ? "" : "Введите текущий пароль.") ||
      passwordError(form.next, username) ||
      matchError(form.next, form.confirm) ||
      (form.next === form.current ? "Новый пароль должен отличаться от текущего." : "");
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    try {
      await api.changePassword({
        current_password: form.current,
        new_password: form.next,
        new_password_confirm: form.confirm,
      });
      onDone();
    } catch (requestError) {
      if (requestError.status === 401) {
        // The session ended elsewhere: the app should show the login screen, not this dialog.
        onExpired?.();
        return;
      }
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="dialog-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
    >
      <form
        className="dialog-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="password-dialog-title"
        onSubmit={save}
        noValidate
      >
        <div className="dialog-top">
          <h2 id="password-dialog-title">Сменить пароль</h2>
          <button type="button" className="icon-button" onClick={requestClose} aria-label="Закрыть">
            <Icon name="close" />
          </button>
        </div>
        <p className="dialog-lead">После смены все остальные сессии будут завершены.</p>

        <input
          type="text"
          name="username"
          autoComplete="username"
          value={username || ""}
          readOnly
          tabIndex={-1}
          aria-hidden="true"
          style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none" }}
        />

        <label className="field-label" htmlFor="current-password">Текущий пароль</label>
        <div className="input-wrap">
          <input
            id="current-password"
            ref={firstFieldRef}
            type="password"
            autoComplete="current-password"
            value={form.current}
            onChange={update("current")}
          />
        </div>

        <label className="field-label" htmlFor="new-password">Новый пароль</label>
        <div className="input-wrap">
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={form.next}
            onChange={update("next")}
          />
        </div>

        <label className="field-label" htmlFor="confirm-new-password">Подтвердите пароль</label>
        <div className="input-wrap">
          <input
            id="confirm-new-password"
            type="password"
            autoComplete="new-password"
            value={form.confirm}
            onChange={update("confirm")}
          />
        </div>

        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}

        <div className="dialog-actions">
          <button type="button" className="button button-secondary" onClick={requestClose} disabled={saving}>
            Отмена
          </button>
          <button className="button button-primary" disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить пароль"}
          </button>
        </div>
      </form>
    </div>
  );
}
