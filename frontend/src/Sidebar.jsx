import { Brand, Icon } from "./Icons.jsx";

export function Sidebar({
  page,
  setPage,
  user,
  onLogout,
  onChangePassword,
  mobileOpen,
  setMobileOpen,
}) {
  const items = [
    { id: "overview", label: "Обзор", icon: "chart" },
    { id: "customers", label: "Клиенты", icon: "users" },
    { id: "model", label: "Модель риска", icon: "edit" },
  ];
  const fullName =
    [user?.first_name, user?.last_name].filter(Boolean).join(" ") ||
    user?.username ||
    "Аналитик";
  const initial = (user?.first_name || user?.username || "A").slice(0, 1).toUpperCase();
  return (
    <>
      {mobileOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Закрыть меню"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside className={`sidebar${mobileOpen ? " sidebar-open" : ""}`}>
        <div className="sidebar-brand">
          <Brand inverse />
        </div>
        <nav className="main-nav" aria-label="Основная навигация">
          {items.map((item) => (
            <button
              key={item.id}
              className={`nav-item${page === item.id ? " nav-item-active" : ""}`}
              onClick={() => {
                setPage(item.id);
                setMobileOpen(false);
              }}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {page === item.id && <span className="nav-active-mark" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-divider" />
        <div className="sidebar-bottom">
          <div className="demo-status">
            <span className="status-indicator" />
            <span>
              <b>Демо-данные</b>
            </span>
          </div>
          <div className="sidebar-user">
            <span className="avatar">{initial}</span>
            <span className="user-copy">
              <b>{fullName}</b>
              <small>{user?.username ? `@${user.username}` : "Аналитик"}</small>
            </span>
            <button
              className="icon-button logout-button"
              aria-label="Выйти"
              title="Выйти"
              onClick={onLogout}
            >
              <Icon name="logout" size={17} />
            </button>
          </div>
          <button
            className="sidebar-link"
            onClick={() => {
              setMobileOpen(false);
              onChangePassword();
            }}
          >
            <Icon name="key" size={16} />
            Сменить пароль
          </button>
        </div>
      </aside>
    </>
  );
}
