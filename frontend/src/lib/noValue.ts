/**
 * The mark a figure's cell carries when the engine produced none.
 *
 * Re-exported from `formatters.ts`, where it now lives. It was defined here and imported by
 * thirty call sites, which is the right dependency for them and the wrong one for the
 * formatters: the four formatters could not import it without creating a specifier that
 * node's ESM resolver rejects, so they carried their own mark instead and the product
 * rendered a missing figure two different ways depending on which component asked.
 *
 * The argument for the value itself is unchanged and is kept where the definition now is.
 */

export { NO_VALUE } from './formatters.ts'
