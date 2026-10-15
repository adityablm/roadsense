import { useEffect, useState } from "react";
import { onSlowChange } from "../api.js";

// Shown when the server is slow to answer, which usually means it was asleep.
export default function WakingNotice() {
  const [slow, setSlow] = useState(false);
  useEffect(() => onSlowChange(setSlow), []);
  if (!slow) return null;
  return (
    <div className="waking" role="status">
      Starting the server. Free servers sleep when nobody is using them, so the first request can take up to a minute.
    </div>
  );
}
