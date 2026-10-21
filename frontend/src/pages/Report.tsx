import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading, SampleBanner, WakingBanner } from "../components/Status";
import { useAppState, usePageData } from "../state";

export default function Report() {
  const { state, error: stateError, retry } = useAppState();
  const { data, error, reload } = usePageData(api.report);

  const brand = state?.brand_name ?? "";

  useEffect(() => {
    document.body.classList.add("report");
    return () => document.body.classList.remove("report");
  }, []);

  useEffect(() => {
    document.title = `${brand} — Daily Report`;
  }, [brand]);

  const failure = stateError ?? error;

  return (
    <>
      <SampleBanner />
      <WakingBanner />
      <div className="previewbar">
        <span>Agency preview of the brand view — internal controls hidden</span>
        <Link to="/">Back to dashboard</Link>
      </div>

      <article className="page">
        <div className="letterhead">
          <div className="leaf">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 19c0-8 5-14 15-14 0 10-6 15-14 15" />
              <path d="M5 19 13 11" />
            </svg>
            {brand}
          </div>
          <span className="ro">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
              <rect x="2.5" y="5.5" width="7" height="5" rx="1" />
              <path d="M4 5.5V4a2 2 0 0 1 4 0v1.5" />
            </svg>
            Read-only · brand view
          </span>
        </div>

        <div className="titleblock" style={{ gap: 12 }}>
          {state && <h1>{brand} — Daily Report</h1>}
          {state && (
            <p className="date">
              {state.campaign_name} · Day <span>{state.current_day}</span> of {state.duration_days}
            </p>
          )}
        </div>

        {failure && <ErrorBox message={failure} onRetry={stateError ? retry : reload} />}
        {!data && !failure && <Loading />}
        {data && (
          <>
            <p className="narrative">{data.text}</p>
            <div className="cols">
              <section className="box" aria-labelledby="hl">
                <h2 id="hl" className="good">
                  Highlights
                </h2>
                {data.highlights.length ? (
                  <ul>
                    {data.highlights.map((item, i) => (
                      <li key={i}>
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#2E7D4F" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M3 8.5 6.5 12 13 4.5" />
                        </svg>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="none">None yet.</p>
                )}
              </section>
              <section className="box" aria-labelledby="is">
                <h2 id="is" className="warn">
                  Issues
                </h2>
                {data.issues.length ? (
                  <ul>
                    {data.issues.map((item, i) => (
                      <li key={i}>
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#A86A00" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                          <path d="M8 4v5" />
                          <path d="M8 12h.01" />
                        </svg>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="none">None.</p>
                )}
              </section>
            </div>
          </>
        )}

        <p className="foot">Prepared by your agency team. Figures update once a day.</p>
      </article>
    </>
  );
}
