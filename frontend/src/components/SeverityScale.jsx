import { LEVELS } from "../labels.js";

// Severity drawn like a painted kerb: 10 blocks, filled up to the score.
export default function SeverityScale({ score, level, size = "normal" }) {
  const filled = Math.round(score);
  const color = LEVELS[level]?.color || LEVELS.none.color;
  return (
    <div className={`scale scale-${size}`}>
      <div className="scale-blocks" role="img" aria-label={`Severity ${score} out of 10, ${LEVELS[level]?.name || level}`}>
        {Array.from({ length: 10 }, (_, i) => (
          <span key={i} style={i < filled ? { background: color } : undefined} />
        ))}
      </div>
      <span className="scale-text">
        <strong style={{ color }}>{LEVELS[level]?.name || level}</strong> {score.toFixed(1)} / 10
      </span>
    </div>
  );
}
