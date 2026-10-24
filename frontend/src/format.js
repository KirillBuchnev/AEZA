export const money = (minor = 0) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
  }).format((minor || 0) / 100);

export const moneyShort = (minor = 0) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(
    Math.round((minor || 0) / 100),
  );

export const dateLabel = (value) =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "short",
      }).format(new Date(value))
    : "Дата не указана";

export const timeLabel = (value) =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(value))
    : "—";

export const plural = (count, [one, few, many]) => {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
};

export const riskText = {
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
  unscored: "Нет оценки",
};
export const riskClass = (level) => level || "unscored";
export const featureOrder = [
  "autoprolong_disabled",
  "insufficient_balance",
  "renewal_urgency",
  "prolong_wait",
];

// Порядок признаков берём из настроек модели, чтобы новые признаки бэкенда
// появлялись в панели без правки фронтенда.
export const featureCodes = (settings) => {
  const codes = Object.keys(settings?.weights || {});
  return [
    ...featureOrder.filter((code) => codes.includes(code)),
    ...codes.filter((code) => !featureOrder.includes(code)),
  ];
};

export const serviceStatusText = {
  active: "Активна",
  suspended: "Выключена",
  prolong_wait: "Ждёт оплаты",
  deleted: "Удалена",
  blocked: "Заблокирована",
};

export const paymentTermText = {
  hour: "Почасово",
  week: "Еженедельно",
  month: "Ежемесячно",
  quarter_year: "Раз в квартал",
  half_year: "Раз в полгода",
  year: "Раз в год",
};
