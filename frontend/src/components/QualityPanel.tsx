import type { Quality } from '../api';

export function QualityPanel({ quality }: { quality?: Quality | null }) {
  if (!quality) return null;
  const { nodes, edges, matchedShapes, warnings, errors } = quality.counts;
  return (
    <section className="quality" aria-label="图纸质量检查">
      <h3>图纸质量检查</h3>
      <p>{nodes} 个设备 · {edges} 条连接 · {matchedShapes} 项素材匹配 · {warnings} 条提示 · {errors} 个错误</p>
      {quality.issues.length > 0 && (
        <details open={errors > 0}>
          <summary>检查明细</summary>
          <ul>
            {quality.issues.map((issue, i) => (
              <li key={i}><b>{issue.code}</b> {issue.message} {issue.relatedIds.join('、')}</li>
            ))}
          </ul>
          {quality.truncated && <p>明细已达到显示上限。</p>}
        </details>
      )}
    </section>
  );
}
