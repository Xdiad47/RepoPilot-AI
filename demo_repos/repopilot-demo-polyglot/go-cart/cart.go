package shop

// ApplyDiscount returns the total after taking percent (0-100) off.
func ApplyDiscount(total float64, percent float64) float64 {
	return total - total*percent/10
}

// Subtotal adds up the line prices.
func Subtotal(prices []float64) float64 {
	sum := 0.0
	for _, p := range prices {
		sum += p
	}
	return sum
}
