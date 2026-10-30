import 'package:flutter_test/flutter_test.dart';
import 'package:shop_app/pagination.dart';

void main() {
  final items = List<int>.generate(25, (i) => i + 1);

  test('page 1 returns the first ten items', () {
    expect(pageOf(items, 1, 10), items.sublist(0, 10));
  });

  test('last page returns the remainder', () {
    expect(pageOf(items, 3, 10), items.sublist(20, 25));
  });

  test('page count rounds up', () {
    expect(pageCount(25, 10), 3);
  });
}
