import { Brand, Icon } from "./Icons.jsx";

export function Sidebar({
  page,
  setPage,
  user,
  onLogout,
  mobileOpen,
  setMobileOpen,
}) {
  const items = [
    { id: "overview", label: "Обзор", icon: "grid" },
    { id: "customers", label: "Клиенты", icon: "users" },
    { id: "model", label: "Модель риска", icon: "sliders" },
  ];
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
          <Brand />
        </div>
        <div className="workspace-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
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
        <div className="sidebar-tip">
          <span className="tip-kicker">КАК ЭТО РАБОТАЕТ</span>
          <p>
            Риск помогает заметить, кому может понадобиться помощь до продления.
          </p>
          <button
            onClick={() => {
              setPage("model");
              setMobileOpen(false);
            }}
          >
            Настроить оценку <Icon name="arrow" size={15} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <div className="demo-status">
            <span className="status-indicator" />
            <span>
              <b>Демо-данные</b>
              <small>Пример клиентского снимка</small>
            </span>
          </div>
          <div className="sidebar-user">
            <span className="avatar">
              {(user?.username || "A").slice(0, 1).toUpperCase()}
            </span>
            <span className="user-copy">
              <b>{user?.username || "Аналитик"}</b>
              <small>Аналитик</small>
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
        </div>
      </aside>
    </>
  );
}
