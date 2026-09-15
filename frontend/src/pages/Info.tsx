export const CAN_DO_ITEMS = [
  "See which public sites appear to have an email or username.",
  "Pull extra social/account profile URLs from Maigret and open-source SpiderFoot (not HX).",
  "Surface Gravatar and public Maigret display photos in the report (no image scraping).",
  "Parse a phone into country, carrier dataset, and line type.",
  "Hand you Google / DuckDuckGo / LinkedIn dorks for manual follow-up.",
];

export function Info() {
  return (
    <div>
      <section className="hero">
        <p className="kicker">Desk notes</p>
        <h2>What this can do</h2>
        <p className="lede">
          Public, open-source checks only. Empty modules stay empty. More detail lives
          in Catalog for each scanner.
        </p>
      </section>
      <article className="panel">
        <h3>What this can do</h3>
        <ul className="limits">
          {CAN_DO_ITEMS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </article>
    </div>
  );
}
