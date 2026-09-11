import { useEffect, useState } from "react";

const KEY = "osint-desk-ethics-v1";

export function EthicsNotice() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem(KEY)) setOpen(true);
  }, []);

  if (!open) return null;

  return (
    <div className="modal-backdrop" role="dialog" aria-labelledby="ethics-title">
      <div className="modal">
        <p className="kicker">Access protocol</p>
        <h2 id="ethics-title">Ethical use required</h2>
        <p>
          OSINT Desk only queries public endpoints and open-source tools. It is
          not a government records system, and it will not invent addresses or
          secret dossiers.
        </p>
        <ul>
          <li>Use it on your own data, with consent, or for authorized investigations.</li>
          <li>Do not stalk, harass, doxx, or target private people without a lawful purpose.</li>
          <li>Empty modules mean no public hit — not that a person has no accounts.</li>
          <li>Paid scrapers and stolen credential dumps are intentionally not wired.</li>
        </ul>
        <div className="modal-actions">
          <button
            className="btn"
            type="button"
            onClick={() => {
              localStorage.setItem(KEY, "accepted");
              setOpen(false);
            }}
          >
            I will use this ethically
          </button>
        </div>
      </div>
    </div>
  );
}
