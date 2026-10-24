export const money = (minor = 0) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
  }).format((minor || 0) / 100);

export const points = (value = 0) =>
  new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  }).format(value || 0);

export const dateLabel = (value) =>
  value
    ? new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "short",
      }).format(new Date(value))
    : "Дата не указана";

export const riskText = {
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
  unscored: "Нет оценки",
};
export const riskClass = (level) => level || "unscored";
export const featureOrder = [
  "prolong_wait",
  "autoprolong_disabled",
  "insufficient_balance",
  "failed_prolong_payment",
];
