import { useEffect } from "react";
import { api } from "../api";
import { ErrorBox, Loading } from "../components/Status";
import { usePageData } from "../state";

export default function Decisions() {
  const { data, error, reload } = usePageData(api.decisions);

  useEffect(() => {
    document.title = "Decision Log · Post-Live Watch";
  }, []);

  return (
    <main className="wrap">
      <div className="head">
        <div className="titleblock">
          <p className="eyebrow">Audit trail</p>
          <h1>Decision Log</h1>
        </div>
        <p className="meta mono">Newest first</p>
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!data && !error && <Loading />}
      {data && (
        <div className="tablebox">
          <table className="top">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Creator</th>
                <th scope="col">Rule</th>
                <th scope="col">Action</th>
                <th scope="col">Message sent</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((d) => (
                <tr key={d.id}>
                  <td className="ts">{d.created_at.slice(0, 16).replace("T", " ")}</td>
                  <td className="h">@{d.handle}</td>
                  <td>{d.rule_name ?? <span className="null">— no rule</span>}</td>
                  <td>
                    <span className={`act-chip a-${d.action}`}>{d.action}</span>
                  </td>
                  <td className="msg">{d.message_text || <span className="null">— no message</span>}</td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <span className="null">No decisions yet. Approve, edit or dismiss a card in the Flag Queue.</span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
