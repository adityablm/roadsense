import { DAMAGE, damageName } from "../labels.js";

// A photo with the model's boxes drawn on top.
// Box positions come from the server as fractions (0 to 1) of the photo's width and height,
// so they line up at any display size.
export default function DetectionImage({ src, detections = [], alt, possible = false }) {
  return (
    <figure className="detect">
      <img src={src} alt={alt} loading="lazy" />
      {detections.filter((d) => d.box).map((d, i) => {
        const [x1, y1, x2, y2] = d.box;
        const color = DAMAGE[d.label]?.color || "#23262a";
        return (
          <div
            key={i}
            className={`detect-box${possible || d.possible ? " detect-box-possible" : ""}`}
            style={{
              left: `${x1 * 100}%`,
              top: `${y1 * 100}%`,
              width: `${(x2 - x1) * 100}%`,
              height: `${(y2 - y1) * 100}%`,
              borderColor: color,
            }}
          >
            <span style={{ background: color }}>
              {possible || d.possible ? "Possible " : ""}{damageName(d.label).toLowerCase()} {Math.round(d.confidence * 100)}%
            </span>
          </div>
        );
      })}
    </figure>
  );
}
