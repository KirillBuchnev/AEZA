export const money = (minor = 0) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
  }).format((minor || 0) / 100);

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
  "payment_distress",
  "manual_renewal",
  "renewal_urgency",
  "grace_period_progress",
];
