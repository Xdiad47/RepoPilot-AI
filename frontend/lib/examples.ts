import { DEMO_REPO_URL } from "@/lib/config";

export interface ExampleBug {
  id: string;
  title: string;
  hint: string;
  repository_url: string;
  bug_description: string;
  stack_trace?: string;
}

/** One-click examples that run against the public demo repository (it contains four deliberate bugs). */
export const EXAMPLES: ExampleBug[] = [
  {
    id: "empty-email",
    title: "Empty email → 500 error",
    hint: "Input validation",
    repository_url: DEMO_REPO_URL,
    bug_description:
      "Signup returns a 500 error when the user submits an empty email address. It should be rejected with a validation error instead of crashing.",
    stack_trace:
      'Traceback (most recent call last):\n  File "shop/validators.py", line 9, in extract_domain\n    return email.strip().split("@")[1].lower()\nIndexError: list index out of range',
  },
  {
    id: "pagination",
    title: "Pagination skips items",
    hint: "Off-by-one",
    repository_url: DEMO_REPO_URL,
    bug_description:
      "On the product list, page 1 skips the first items and the last page comes back empty. With 25 products and 10 per page I expect pages of 10, 10 and 5.",
  },
  {
    id: "dashboard",
    title: "Dashboard crashes with no orders",
    hint: "Edge case",
    repository_url: DEMO_REPO_URL,
    bug_description:
      "The shop dashboard crashes with a ZeroDivisionError for new shops that have no orders yet. Also the median of an even number of orders looks wrong.",
  },
  {
    id: "discount",
    title: "10% discount takes 100% off",
    hint: "Wrong arithmetic",
    repository_url: DEMO_REPO_URL,
    bug_description:
      "A 10% discount on a 200 dollar cart takes off the entire price and the total shows 0.0 instead of 180.",
  },
];
