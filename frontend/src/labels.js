// Human-friendly names and colours, shared by every page.

export const DAMAGE = {
  pothole: { name: "Pothole", color: "#c62f1c" },
  alligator_crack: { name: "Alligator crack", color: "#d97a06" },
  transverse_crack: { name: "Crack across the road", color: "#1f5aa6" },
  longitudinal_crack: { name: "Crack along the road", color: "#6b4fa0" },
};

export const LEVELS = {
  severe: { name: "Severe", color: "#c62f1c" },
  moderate: { name: "Moderate", color: "#d97a06" },
  minor: { name: "Minor", color: "#5e8c31" },
  none: { name: "No damage", color: "#6f747a" },
};

export const damageName = (label) => DAMAGE[label]?.name || label.replace(/_/g, " ");

export function formatDate(value) {
  return new Date(value).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export const formatCoord = (lat, lng) => `${lat.toFixed(5)}, ${lng.toFixed(5)}`;

// Hyderabad city centre, where the map starts.
export const HOME = { lat: 17.385, lng: 78.4867, zoom: 12 };
