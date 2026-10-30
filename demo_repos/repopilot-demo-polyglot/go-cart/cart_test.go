package shop

import "testing"

func TestApplyDiscount(t *testing.T) {
	if got := ApplyDiscount(200, 10); got != 180 {
		t.Fatalf("ApplyDiscount(200, 10) = %v, want 180", got)
	}
}

func TestSubtotal(t *testing.T) {
	if got := Subtotal([]float64{1.5, 2.5}); got != 4 {
		t.Fatalf("Subtotal = %v, want 4", got)
	}
}
