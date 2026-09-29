/**
 * The mark a figure's cell carries when the engine produced none.
 *
 * A bare dash is the old convention and it was wrong here for a specific reason
 * rather than a stylistic one. These are financial tables, so a horizontal
 * stroke already means a negative number: -5.0% and "no figure at all" were
 * both a dash, in the same column, at the same size. A reader scanning for
 * downside could not tell a loss from a gap, and a screen reader announced the
 * same word for both.
 *
 * "n/a" is unambiguous in both channels and says what is true, which is that
 * the engine declined to produce a figure rather than that the figure is zero.
 * Every cell using it is a cell where a reader needs exactly that distinction.
 */
export const NO_VALUE = 'n/a'
