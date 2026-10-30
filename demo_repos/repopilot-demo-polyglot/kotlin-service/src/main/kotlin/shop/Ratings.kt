package shop

/** Average star rating shown on a profile; 0.0 when there are no ratings yet. */
fun averageRating(ratings: List<Int>): Double {
    return ratings.sum() / ratings.size.toDouble()
}

fun roundToHalf(value: Double): Double = Math.round(value * 2) / 2.0
