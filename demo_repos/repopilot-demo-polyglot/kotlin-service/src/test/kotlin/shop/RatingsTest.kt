package shop

import kotlin.test.Test
import kotlin.test.assertEquals

class RatingsTest {
    @Test
    fun averageOfSeveral() = assertEquals(4.0, averageRating(listOf(5, 3, 4)))

    @Test
    fun emptyListIsZero() = assertEquals(0.0, averageRating(emptyList()))
}
