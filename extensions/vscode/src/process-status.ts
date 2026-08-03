/** Classify recoverable local CLI outcomes without exposing implementation traces in UI. */
export const cacheBusy = (value: string): boolean => /CacheBusyError|analysis state is owned by pid|cache[ _-]?busy/iu.test(value);
export const partialAnalysis = (value: string): boolean => /interrupted_write|partial (analysis|cache)|incomplete cache/iu.test(value);

export function processFailure(operation: "Analysis" | "Review", result: { stdout: string; stderr: string }): string {
  const detail = [result.stderr, result.stdout].filter(Boolean).join("\n");
  if (cacheBusy(detail)) return `${operation} is blocked because another local CodeSlicer analysis still owns this project. No result was accepted. Wait for that process to finish, then Refresh; locks from dead processes recover automatically.`;
  if (partialAnalysis(detail)) return `${operation} rejected an interrupted or partial cache. No partial result was accepted; refresh and run it again.`;
  // Keep technical stack traces in the opt-in Output channel. A notification
  // must describe the actionable state rather than turn a recoverable failure
  // into an unreadable wall of implementation detail.
  if (/Traceback \(most recent call last\)|\bat \S+ \(/u.test(detail)) return `${operation} failed. See the CodeSlicer Output channel for the technical log.`;
  // CLI text is diagnostic material, not UI copy.  In particular argparse can
  // echo a full command line or paths from an external runtime.  Keep it in
  // Output and give the user one stable, actionable message here.
  return `${operation} failed. See the CodeSlicer Output channel for the technical log.`;
}
