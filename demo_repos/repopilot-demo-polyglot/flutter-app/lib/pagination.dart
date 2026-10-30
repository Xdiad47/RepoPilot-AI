/// Returns the items for a 1-based [page] of size [pageSize].
List<T> pageOf<T>(List<T> items, int page, int pageSize) {
  final start = page * pageSize;
  final end = start + pageSize;
  if (start >= items.length) return <T>[];
  return items.sublist(start, end > items.length ? items.length : end);
}

/// Number of pages needed for [total] items.
int pageCount(int total, int pageSize) => (total / pageSize).ceil();
