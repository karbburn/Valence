from __future__ import annotations

from typing import Tuple, Dict, FrozenSet

# Labels deliberately NOT mapped, and which must stay unmapped.
#
# WITHDRAWN_LABELS exists because removing an entry from RAW_METRIC_MAP does not
# actually withdraw it. `map_raw_datapoints` falls through to the confidence engine
# when the registry returns None, and that engine proposes these very labels at
# MEDIUM confidence:
#
#     "Investments"  -> canonical.bs.non_current_investments
#     "Other Assets"  -> canonical.bs.other_non_current_assets
#
# So the withdrawals recorded in this file were inert. Screener's "Investments"
# aggregate kept publishing -- it simply moved from the current-asset key to the
# non-current one, so Infosys showed 21,880 of non-current investments against a
# filed 8,930 and the double count survived the fix that was meant to end it.
#
# A medium-confidence suggestion is a guess, and it must not overrule a decision
# that was made on evidence. Each label here is one where the figure is an AGGREGATE
# the filer did not print as a caption, so mapping it to a narrow key states
# something the engine does not know. The reasoning for each is at its would-be entry
# below; `current_assets_reconcile` reports the resulting shortfall.
#
# "Other equity" and "Equity attributable to shareholders of the Company" are the
# same class of error from the other direction: genuine filed captions the engine
# maps to the WRONG key. TCS prints Share capital 362 + Other equity 106,878 =
# Equity attributable 107,240, + Non-controlling 1,238 = Total equity 108,478
# (FY26 consolidated), yet the engine suggests "Other equity" -> total_equity at
# 0.58 and the rupee subtotal "Equity attributable..." -> share_count at 0.47, and
# the mapper accepts both. The first double-counts the total; the second puts
# rupees in a share-count key. Neither has an unambiguous home in the current
# key set -- "Other equity" is a component with no component key, and the
# attributable subtotal differs from the total by the minority interest -- so both
# stay withdrawn until those keys exist.
#
# HCLTech's liabilities face adds three more of the same family, found by parsing
# printed page 6 caption by caption. "Equity attributable to owners of the Company"
# (7,761) is suggested to net_profit at 0.57 -- an equity subtotal mapped into the
# profit-and-loss statement, worse than the share_count case because the key is at
# least a rupee key. "Deferred tax liabilities (net)" (152) and "Current tax
# liabilities (net)" (363) are suggested to the corresponding ASSET keys at 0.58 --
# liabilities mapped across the balance sheet into assets. No liability key exists
# for either, and a liability parked in an asset key inverts the statement, so all
# three stay withdrawn. The current-liabilities face foots exactly (3,099) WITH these
# rows present, which is what makes their absence from the model a recorded shortfall
# rather than a rounding difference.
WITHDRAWN_LABELS: FrozenSet[str] = frozenset({
    "Investments",
    "Other Assets",
    "Other equity",
    "Equity attributable to shareholders of the Company",
    "Equity attributable to owners of the Company",
    "Deferred tax liabilities (net)",
    "Current tax liabilities (net)",
    # TCS consolidated face (p.11), same two-figures-one-key shape as the
    # Employee benefit obligations withdrawal, measured caption by caption:
    # "Loans" prints 775 non-current against 1,659 current, "Other assets"
    # 2,605 against 16,533, "Other financial assets" 2,944 against 1,833,
    # "Other financial liabilities" 588 against 11,194 -- no key exists for
    # any of them, and one key would hold whichever half parsed last.
    # "Income tax liabilities (net)" (14,751 / 12,715, current only) shares
    # the fate of "Current tax liabilities (net)" above: no tax-liability
    # key exists, and a liability parked in an asset key inverts the
    # statement. "Unearned and deferred revenue" prints 647 non-current
    # against 4,487 current; the key is a current-liabilities line the
    # half guard does not claim, so the tie would publish the non-current
    # 647 as current. All six stay out; the current halves they shadow are
    # not recoverable without half-specific keys that do not exist.
    "Loans",
    "Other assets",
    "Other financial assets",
    "Other financial liabilities",
    "Income tax liabilities (net)",
    "Unearned and deferred revenue",
    # Two more the reported boost would otherwise promote wrongly, found by
    # measuring every multi-candidate cell before landing the rule. "Cash flow
    # hedge reserves" is a component the registry parked on the
    # other_reserves total (6 publishing as 86,045 at FY24); "Administrative
    # expenses" is the admin half of a selling-and-admin key whose selling
    # half the filing never prints, and the derivation below refuses to build
    # the combined total from one half. Both keep today's published figures;
    # the filed parts stay out rather than publishing as wholes they are not.
    "Cash flow hedge reserves",
    "Administrative expenses",
    # A second family: captions the FILER prints, read from the statement pages
    # themselves, where either no canonical key exists or the label cannot pick
    # one. Withdrawn rather than left unmapped because an unmapped caption reads
    # as an accident and these are decisions; the review queue records the name
    # either way.
    #
    # Cash-flow and OCI detail the model does not consume. The section totals they
    # roll into are mapped from the filing's own subtotal captions, so the statement
    # is complete without them, and the suggestion engine rates every one of these
    # low confidence (0.2, no key), so there is no adjacent key quietly waiting to
    # absorb them. The one adjacent-looking case is recorded here rather than
    # mapped: "Expenditure on property, plant and equipment and intangibles" is the
    # filing's capex line, and two documents word it differently for the same year
    # ("... and intangibles" against "... and intangibles, net of sale proceeds"),
    # so a single capex key would hold whichever caption parsed last under a
    # meaning that differs by document. Filling capex would also give the forecast
    # a new anchor where it currently falls back to depreciation, which is a
    # product decision, not a lookup.
    "Deposits placed with corporation",
    "Redemption of deposits placed with corporation",
    "Expenditure on property, plant and equipment and intangibles",
    "Expenditure on property, plant and equipment and intangibles, net of sale proceeds (Refer",
    "Impairment loss recognized/(reversed) under expected credit loss model",
    "Exchange differences on translation of assets and liabilities, net",
    "Other receipts",
    "Other payments",
    "Loan repayment of in-tech Holding GmbH",
    "Loan repayment of in-tech Holding GmbH (Refer to note 2.10)",
    "Shares issued on exercise of employee stock options",
    "Payment of dividends to non-controlling interests of subsidiary",
    "Payment towards purchase of non-controlling interest",
    # Comprehensive income and its components. The key set has no comprehensive-
    # income entry, so there is nowhere honest to file them, and "Equity
    # instruments through other comprehensive income, net" is printed on the
    # income-statement page while being an equity balance, which is the
    # cross-statement mistake the caption check exists to prevent.
    "Total comprehensive income",
    "Total other comprehensive income/(loss), net of tax",
    "Equity instruments through other comprehensive income, net",
    "Exchange differences on translation of foreign operations",
    "Fair value changes on investments, net",
    "Remeasurement of the net defined benefit liability/asset, net",
    # Balance-sheet lines without one unambiguous home. "Employee benefit
    # obligations" is printed TWICE per document under the same words with
    # different amounts (3,524 non-current against 117 current at FY26), and both
    # rows arrive tagged [noncurrent], so one key would hold two figures for one
    # period and the winner would be row order -- the ambiguity `bs_half` exists
    # to answer, which a label mapping cannot. "Share premium" and "Other
    # components of equity" are the two sibling lines the filing prints between
    # retained earnings and the attributable total (p.100, y=46 and y=50), and
    # measured against the reserves key they score exactly what the key's own
    # "Other reserves" caption scores (reported + regulatory + positive, no
    # section string in an NSE source_location, neither a primary label), so the
    # tie would break by archive order -- and the caption printed highest on the
    # page would publish, replacing the line the key is named for with a
    # component of it. The filer's own caption keeps the key; the two beside it
    # stay out, and the gap against the filed total (8,370 at FY26: these two,
    # the capital redemption reserve shadowed in the same tie, and the hedge)
    # is a recorded shortfall rather than an aggregate restated as a part.
    # "Right-of-use assets" has no key at all.
    "Right-of-use assets",
    "Share premium",
    "Other components of equity",
    "Employee benefit obligations",
    # Third family: captions the engine does reach, at the wrong destination.
    # Each is a real printed line whose only suggestion states something false
    # about it, so the mapping is withdrawn rather than accepted, and the wrong
    # figure stays out of the model the same way as the families above. All
    # five are printed only by Infosys; no other company's rows are touched.
    #
    # "Cash generated from operations" (35,297 / 42,388 / 44,472) is the
    # operating section's pre-tax subtotal, and the filing prints the section's
    # own total on the line below it ("Net cash generated by operating
    # activities", 26,066 / 36,786 / 35,824): the two differ by exactly the
    # taxes-paid line the statement prints separately (9,231 / 5,602 / 8,648).
    # Both captions suggest operating_activities at the same score, so which
    # figure the key would publish is row order, and the pre-tax one is the
    # wrong answer for a line the statement labels Cash Flow from Operating
    # Activities.
    "Cash generated from operations",
    # "Deferred income tax liabilities" (1,794 / 1,722 / 1,679) is parked on
    # the DEFERRED TAX ASSET key. No liability key exists -- the same reason
    # HCLTech's "Deferred tax liabilities (net)" is withdrawn above -- and the
    # asset row wins each period only because assets print above liabilities
    # on the page, which is order again rather than evidence. A liability
    # parked in an asset key inverts the statement.
    "Deferred income tax liabilities",
    # "Interest and dividend income" ((1,138) / (1,168) / (1,125)) is the
    # operating-section adjustment that removes that income from profit before
    # tax, and the engine parks it on the Interest & Dividends Received line,
    # which counts cash coming in. The filing prints the cash line too
    # ("Interest and dividend received", 912 / 948 / 875), which is mapped, and
    # it wins each period today only on the positive-value boost; a deduction
    # should not be a rival of the receipt it adjusts.
    "Interest and dividend income",
    # "Total equity attributable to equity holders of the Company"
    # (88,116 / 95,818 / 92,852) is the total LESS non-controlling interests
    # (345 / 385 / 445, exact in all three years), and the engine parks it on
    # total_equity beside the filing's own "Total equity" caption
    # (88,461 / 96,203 / 93,297, mapped above). The primary-label boost keeps
    # the inclusive figure selected, but a component beside its own total in
    # one key is the "Other equity" shape recorded at the top of this file, and
    # there is no key for the attributable subtotal.
    "Total equity attributable to equity holders of the Company",
    # "authorized, issued and outstanding 4,143,607,528 (4,139,950,635) equity"
    # (2,071 / 2,073) is the equity share capital row read together with its
    # share-count note text; the figure itself is printed again by the filer's
    # own "Equity Share Capital" caption for the same periods (2,071 / 2,073,
    # mapped above), so nothing is lost by refusing the fragment, and the
    # engine parks it on total liabilities and equity.
    "authorized, issued and outstanding 4,143,607,528 (4,139,950,635) equity",
    # One more label for a different reason: the cash-flow statement keeps the
    # LAST canonical row it sees for a key and period instead of scoring the
    # candidates, so when both of these captions map to business_acquisitions
    # the page order decides which figure publishes. On the FY26 page the
    # contingent line prints BELOW the acquisition line (y=506.2 under y=495.2)
    # and its (13) overwrites the filing's own (637), so the model published
    # (13) under the label "Payment for Business Acquisitions" while the filing
    # prints (637) on the line that carries that name. The two figures are also
    # different things: the acquisition line is the year's purchases of
    # businesses net of cash acquired, while the contingent line settles
    # consideration for acquisitions already made (the (101) at FY24, the (13)
    # at FY26). With no ordering that prefers authority, the caption that IS
    # the line keeps the key and the settlement detail is withdrawn like the
    # other disclosed detail; the FY24 headline line prints a dash, so that
    # year's cell goes empty instead of holding a settlement. Printed by
    # Infosys only.
    "Payment of contingent consideration pertaining to acquisition of business",
    # And the escrow pair, where the same one-row-per-key rule publishes one
    # side of a movement the filing prints twice. FY26 shows deposits placed
    # (1,815) at y=517.2 and redemptions received 1,815 at y=528.3, netting to
    # zero for the year; the redemption prints last, so the model published
    # 1,815 as the year's escrow line while the deposit sat shadowed, a net
    # cash effect the filing contradicts with its own two lines. No printed
    # figure represents the net, so both captions go, the same disposition as
    # the deposit and redemption pair recorded above without a key. The line is
    # empty for this company rather than showing one side of a pair, and the
    # figures were published this same one-sided way before the migration, so
    # this corrects a standing figure. Printed by Infosys only.
    "Escrow and other deposits pertaining to Buyback",
    "Redemption of escrow and other deposits pertaining to Buyback",
    # HCLTech's audited Ind-AS face (printed page 4), each refused on what that
    # page prints. The captions keep the filer's own numbering, because the
    # letters are load-bearing: the face prints "(c) Provisions" in the
    # non-current block and "(d ) Provisions" in the current one, and one
    # stripped to bare words would be a single caption with two figures.
    #
    # "(c) Right-of-use assets" (3,592 / 3,016): no key exists for a
    # right-of-use asset while every neighbour on that line has one (PP&E,
    # goodwill, intangibles), so parking it in PP&E would state a leased asset
    # as an owned one.
    "(c) Right-of-use assets",
    # "(f) Intangible assets under development" (82): the same block prints
    # "(e) Other intangible assets" onto the intangibles key beside it, and a
    # second caption on one key leaves whichever the reader kept -- the face
    # names these two lines itself.
    "(f) Intangible assets under development",
    # "(iii) Loans" (50 / 586) and "(v) Loans" (1,017 / 976): loan RECEIVABLES
    # on the assets side, and the only loan key is borrowings, which is money
    # the company owes. An asset parked there inverts the statement.
    "(iii) Loans",
    "(v) Loans",
    # The face's four "Others" catch-alls -- "(iv)" at 3,585 non-current assets
    # and 9,228 current liabilities, "(vi)" at 1,626 current assets, "(iii)"
    # at 1,401 non-current liabilities: a remainder bucket with no line it
    # belongs to. There is no key for a filer's own catch-all, and choosing one
    # would name money the filing leaves unnamed.
    "(iv) Others",
    "(vi) Others",
    "(iii) Others",
    # "(iv) Other bank balances" (15,160 / 13,044): deposits, neither cash nor
    # prepayments. On the cash key they would overstate liquid cash by the
    # whole deposit book, so the line goes empty and the shortfall is visible
    # in the reconciliation instead of hiding inside it.
    "(iv) Other bank balances",
    # "(b) Other equity" (74,622 / 69,112): the same decision as this caption's
    # bare form above -- a component with no component key, and `other_reserves`
    # holds the narrower "Other reserves" where another filer prints it. The
    # face's own "TOTAL EQUITY" (75,197 / 69,673) is mapped, so the block still
    # foots to what the filing totals.
    "(b) Other equity",
    # "(i) Borrowings" (37 non-current / 122 current at FY26) and "(ii) Lease
    # liabilities" (3,180 / 1,876) print once in each half under one caption.
    # Borrowings would need the current row routed to the short-term line and
    # cannot be: the page tags both rows the same, so which figure reached the
    # non-current key would be row order. The lease lines are keyed by lease
    # TYPE (operating and finance) and this caption names no type. The
    # lease-borrowings precedent above (TCS) withdraws both for the same
    # reason: one key would hold whichever half parsed last.
    "(i) Borrowings",
    "(ii) Lease liabilities",
    # "(b) Contract liabilities" (1,162 non-current / 5,053 current): no key,
    # and both print under this one caption -- the unearned-revenue key is a
    # current line, so the non-current figure could not reach it honestly and
    # the current one would publish beside a caption the filing does not use.
    "(b) Contract liabilities",
    # "(c) Provisions" (2,001 / 1,920) prints in the NON-current block, and the
    # only provisions key is the current-liabilities line. The face prints
    # "(d ) Provisions" (1,664 / 1,487) in the current block and that caption
    # is mapped; both on one key would collide on every period.
    "(c) Provisions",
    # The two tax-liability captions, refused for the same reason as their bare
    # forms above: no liability key exists, and a liability parked in an asset
    # key inverts the statement. Printed here as "(d) Deferred tax liabilities
    # (net)" (1,381 / 1,615) and "(e) Current tax liabilities (net)"
    # (3,862 / 2,815).
    "(d) Deferred tax liabilities (net)",
    "(e) Current tax liabilities (net)",
    # Reliance's audited consolidated face (printed page 16), each refused on
    # what that page prints. Title case throughout, so none of these matches
    # the lower-case withdrawals above by exact spelling -- and the engine's
    # fuzzy suggestions for them are recorded per caption, because two already
    # published catastrophically in the dry run: an 83,453 liability as a
    # deferred-tax asset, and an 829,668 equity component as the equity total
    # (dooming the true 1,009,626 beside it).
    #
    # "Other Equity" (829,668): the TCS "(b) Other equity" decision in this
    # spelling -- a component with no component key, and `other_reserves`
    # holds the narrower "Reserves" where the screener prints it. The face's
    # own "Total Equity" (1,009,626) is mapped, so the block still foots.
    "Other Equity",
    # "Other Financial Assets" (23,546 current) and "Other Financial
    # Liabilities" (10,909 non-current): the TCS "Other financial assets /
    # liabilities" decision in this spelling -- no key exists for either, and
    # one key would hold whichever half parsed last. The liabilities caption
    # is worse: the engine sends it to `other_current_liabilities`, whose true
    # figure (90,124) the gate then dooms beside it, so withdrawing it frees
    # the true current line.
    "Other Financial Assets",
    "Other Financial Liabilities",
    # The artifact twins "Olher Financial Assets" (6,088 non-current) and
    # "Olher Financial Liabilities" (57,143 current): the same no-key decision
    # under the extracted spelling, where the face's font drops the "t". A
    # mapped twin beside each clean sibling would put two figures on one key,
    # so both stay out like HCLTech's "(iv) Others" that prints in both blocks.
    "Olher Financial Assets",
    "Olher Financial Liabilities",
    # "Deferred Tax liabilities (Net)" (83,453): the HCL "(d) Deferred tax
    # liabilities (net)" decision in this spelling -- no liability key exists,
    # and the engine sends it to the deferred-tax ASSET key, which inverts the
    # statement by the full 83,453 and dooms the true 408 asset beside it.
    "Deferred Tax liabilities (Net)",
    # "Deferred Payment liabilities" (104,410 spectrum dues), "Spectrum"
    # (147,122) and "Spectrum Under Development" (54,176): telecom lines with
    # no key. Spectrum beside "Olher Intangible Assets" on the intangibles key
    # would publish one of two separately-printed lines as the whole, so all
    # three stay out and the shortfall is visible in the reconciliation.
    "Deferred Payment liabilities",
    "Spectrum",
    "Spectrum Under Development",
    # "Other lnlangible Assels Under Development" (38,472): the HCL "(f)
    # Intangible assets under development" decision under the extracted
    # spelling, where "t" extracts as "l" and "t" as "s" in the same line. The
    # face prints completed intangibles onto the intangibles key beside it,
    # and a second caption on one key leaves whichever parsed last.
    "Other lnlangible Assels Under Development",
    # --- ONGC audited consolidated face (printed p.35 + p.36) ---
    #
    # The two tax LIABILITIES, in the HCL and Reliance decision's spelling: the
    # engine sends each to a tax ASSET key, which inverts the statement by the
    # full figure and refuses the true asset beside it in the same bucket.
    # Printed as "(c) Deferred Tax liabilities (net)" (38,765 / 40,655) and
    # "(d) Current Tax Liabilities (net)" (642 / 639).
    "(c) Deferred Tax liabilities (net)",
    "(d) Current Tax Liabilities (net)",
    # The property, plant and equipment block. ONGC prints no PPE total, only
    # the components of it: "(a) Tangible" 157,405, "(b) Intangible" 329 and
    # "(ii) Other property, plant and equipment" 134,068, which together carry
    # the 291,802 the face's own non-current subtotal contains. Publishing any
    # one of them as `ppe` states a component as the whole -- the "(ii)" line
    # alone understates the true figure by more than half -- so all three stay
    # out and the line remains feed-sourced.
    "(a) Tangible",
    "(b) Intangible",
    "(ii) Other property, plant and equipment",
    # The capital-work-in-progress block, same shape: components and no subtotal
    # (exploratory wells 19,586, development wells 4,047, oil and gas facilities
    # 39,524, acquisition cost 21,635, intangible oil and gas assets in progress
    # 5,696, "(ii) Others" 22,084). No key holds a component of a total the
    # filer never prints.
    "(i) Exploratory wells in progress",
    "a) Development wells in progress",
    "b) Oil and gas facilities in progress",
    "c) Acquisition Cost",
    "(ii) Others",
    "(iii) Intangible Oil and Gas Assets in progress",
    # "(vii) Others" (14,957 / 9,868) is the current financial-assets remainder.
    "(vii) Others",
    # "(iii) Right of Use Assets" (34,181 / 30,245): the statement contract has
    # no right-of-use ASSET key -- only the three lease-liability ones -- so the
    # asset stays out while its liability side is refused as a twin.
    "(iii) Right of Use Assets",
    # "(c) Investment Property" (7.87 / 7.70): no key exists.
    "(c) Investment Property",
    # The site-restoration deposits, printed once per half (30,849 non-current,
    # 36 current at FY26), and the held-for-sale pair ("Assets classified as held
    # for sale" 13 / 208 with its directly-associated liabilities 93): no key
    # exists for any of them, and the held-for-sale figures are exactly what
    # bridges the two halves to the 758,729 / 791,905 the face prints as total
    # assets, so they are recorded rather than quietly folded into another line.
    "(iv) Deposit under site restoration fund",
    "(vi) Deposit under site restoration fund",
    "Assets classified as held for sale",
    "Liabilities directly associated with assets classified as held for sale",
    # "(ii) Trade receivables" (21,243 / 22,015) is the NON-CURRENT receivable:
    # the face prints no trade-receivable caption in its current block at all.
    # Publishing it as `trade_receivables` would count a permanently parked
    # figure as liquid, which is the exact under-count `current_assets_reconcile`
    # exists to surface.
    "(ii) Trade receivables",
    # The two micro-enterprise trade-payable splits (1,380 and 37,601 at FY25)
    # with no total printed beside them: one key cannot hold the split, and
    # whichever half published would be a partial payable.
    "- to micro and small enterprises",
    "- to other than micro and small enterprises",
    # "(i) Other Investments" (33,717 / 34,224): the non-current block prints no
    # subtotal and its equity-method sibling above takes the one key.
    "(i) Other Investments",
    # --- Tata Steel audited consolidated face (printed p.20) ---
    #
    # The face letter-spaces its headings, and the extraction keeps only part of
    # several captions. Every refusal below is decided against the figures the
    # page prints beside those words.
    #
    # The four subtotal fragments. The page prints six subtotals and the words
    # that tell them apart were lost: bare "Sub-total" carries FOUR figures --
    # 68,391.54 / 72,265.11 and 91,352.78 / 103,780.45 -- because the
    # current-assets subtotal and the total-equity subtotal extract to the same
    # two words; "Sub-total - Non-current" carries both 211,003.26 / 228,733.94
    # (non-current assets) and 101,948.47 / 100,556.02 (non-current liabilities,
    # printed below the asset headers so the half reads current); "Sub-total -
    # Current" lost the word that says assets or liabilities; "Sub-total -" lost
    # all of them. The printed figures foot -- 211,003.26 + 68,391.54 =
    # 279,394.80 = 101,948.47 + 86,093.55 + 91,352.78 -- but a registry key is
    # chosen from the caption, and the caption says which subtotal only where
    # the words survived.
    "Sub-total",
    "Sub-total -",
    "Sub-total - Current",
    "Sub-total - Non-current",
    # The equity line in this filer's lowercase extraction. The capitalised
    # spelling is already withdrawn because the engine sends it to share_count
    # at 0.47, an equity figure in a share-count field. This page extracts
    # "company" lowercase, both gates match the printed string exactly, and a
    # MEDIUM suggestion publishes -- so without this line 102,167.65 crores
    # would arrive as a share count. No key holds equity excluding
    # non-controlling interests, and the total_equity key would need the
    # 103,780.45 that includes them.
    "Equity attributable to shareholders of the company",
    # The same family decision as HCLTech's "(f)" line: a development-stage
    # figure (986.42 at FY26) stated as recognized intangibles, and this face
    # prints no intangibles subtotal to check the claim against.
    "Intangible assets under development",
    # Enumerator-only fragments: the words are gone, and the enumerator alone
    # is printed by every filer in every block.
    "()",
    "(c)",
    "(iii)",
    "(vi) assets",
    # No key holds any of these lines, so each stays feed-sourced rather than
    # borrowing a neighbour's key: the retirement-benefit pair (the asset
    # prints in both blocks -- 12.67 / 86.38 non-current and 2.33 current --
    # against obligations of 154.62 / 148.63, and its own enumerator is broken
    # in the non-current printing), deferred income in its two extractions
    # (764.91 and 30.71 / 88.09), the derivative LIABILITIES (206.38 and
    # 391.18 / 260.7 -- the only derivative key is an asset key, and parking a
    # liability there inverts the line the way ONGC's tax liabilities were
    # inverted), acceptances (338.52), and the held-for-sale line with no
    # subtotal printed (255.06, withdrawn for the same reason on ONGC's face).
    "( Retirement benefit assets",
    "(c) Retirement benefit assets",
    "(c) Retirement benefit obligations",
    "(d) Deferred income",
    "\u00abd) Deferred income",
    "(iii) Derivative liabilities",
    "(iv) Derivative liabilities",
    "Acceptances",
    "(3) Assets held for sale",
    # --- Wipro audited consolidated face (printed p.21) ---
    #
    # The extraction keeps only the first words of several captions, and on
    # every line below the words that said assets or liabilities are the ones
    # that went. Each refusal is decided against the figures the page prints
    # beside the fragment.
    #
    # "Non-current" carries 42,024 / 48,195: the printed "Non-current tax
    # liabilities (net)". The engine sends the fragment to
    # non_current_investments at medium confidence, which would publish a tax
    # liability as an investment, and no key on this face holds non-current tax
    # liabilities. The asset sibling survives extraction as "Non.current tax"
    # (7,230 / 7,787) and is declined by the statement guard instead, so the
    # fragment is the only row that would reach a wrong key.
    "Non-current",
    # "Other non-current" carries 12,757 / 17,877: the printed "Other
    # non-current liabilities". The engine sends it to
    # other_non_current_assets at medium confidence, parking a liability in the
    # asset column. The asset line extracts as "Other non-cum:nt" (7,707 /
    # 9,451) and is queued unmapped, so nothing here borrows its key.
    "Other non-current",
    # "Total current" carries 286,253 / 403,232: the printed "Total current
    # liabilities". The engine sends it to total_current_assets at medium
    # confidence, where it would collide with the caption that does say assets
    # -- "Total current assets", 777,775 / 826,354, statically mapped -- and
    # the collision refuses both rows. Withdrawing the liability fragment
    # resolves that: the asset subtotal publishes and the liability figure
    # stays a recorded unknown, there being no total-current-liabilities key.
    "Total current",
    # "Equity attributable" is the printed "Equity attributable to the equity
    # holders of the Company": 823,641 / 880,183, the parent-only slice. The
    # engine sends it to total_equity at medium confidence, where it collides
    # with the printed TOTAL EQUITY (825,779 / 882,692, statically mapped),
    # whose figure includes the non-controlling interests of 2,138 / 2,509
    # that this line excludes by definition. No key holds equity excluding
    # non-controlling interests, so the fragment refuses and the total
    # publishes.
    "Equity attributable",
    # --- Sun Pharmaceutical audited consolidated face (printed p.19) ---
    #
    # This face prints its captions in full, so every refusal below is the
    # engine rather than the extraction: three tax liabilities whose only keys
    # are asset keys, one intangible component whose key the completed
    # intangibles beside it already take, and the parent-only equity whose
    # total the sheet prints itself.
    #
    # "(c) Deferred tax liabilities (Net)" carries 1,924.4 / 3,780.2 from the
    # current-liabilities block, and the engine sends it to deferred_tax_assets
    # at medium confidence -- the same inversion ONGC's face recorded, where a
    # 38,765 liability sat on the asset key. The true deferred-tax asset sits
    # on this same face (44,075.5 / 40,464.6) and takes the key below.
    "(c) Deferred tax liabilities (Net)",
    # "(d) Current tax liabilities (Net)" (7,331.8 / 13,500.4) and "(e)
    # Non-current tax liabilities (Net)" (87.6 / 128.9) both reach
    # current_income_tax_assets -- the first directly, the second through
    # income_tax_assets routed by half -- where they collide with each other
    # and refuse both rows. Neither has a liability key, and a liability on an
    # asset key is the inversion, so both refuse and the tax ASSET beside them
    # takes income_tax_assets below.
    "(d) Current tax liabilities (Net)",
    "(e) Non-current tax liabilities (Net)",
    # "(e) Intangible assets under development" (54,096.2 / 16,710.8) and "(d)
    # Other intangible assets" (36,109.2 / 118,750.8) are two distinct lines
    # under one key, and the twin gate would refuse both. Reliance's face made
    # this exact choice: the under-development line is withdrawn there so the
    # completed intangibles publish. One key cannot hold two figures for one
    # period, and the completed line is the one that names what it is.
    "(e) Intangible assets under development",
    # "Equity attributable to the equity shareholders of the parent company"
    # (722,180.2 / 835,700.9) is the parent-only slice, and the printed "Total
    # equity" (724,859.5 / 838,797.4) includes the non-controlling interests
    # of 2,679.3 / 3,096.5 -- the figure closes exactly, 835,700.9 + 3,096.5 =
    # 838,797.4. The engine currently suggests share_count, which a guard
    # declines; the withdrawal makes the refusal structural, the way Wipro's
    # truncated fragment was withdrawn so its printed TOTAL EQUITY publishes.
    "Equity attributable to the equity shareholders of the parent company",
    # --- Bharti Airtel audited consolidated face (printed p.3) ---
    #
    # This page's extraction carries glyph damage in the captions and, in one
    # block, in the values: the FY26 column between "-na.d'e recei:Vabl'es"
    # and the non-current subtotal yields five tokens for six caption slots,
    # so captions from "-Loans" down pair one cell late against the true
    # figures. The page's own subtotals prove it: the non-current assets
    # subtotal 4,619,362 closes exactly over the clean lines plus 191,413 --
    # the single mangled token where the two tax assets print. Each withdrawal
    # below is a caption whose cells cannot be trusted, or whose key the
    # engine gives to a line that is not what it names.
    #
    # "-Other ffinancral' assets" (non-current other financial assets) reads
    # FY25=37,471 correctly and FY26=35,700, a figure the subtotal
    # arithmetic assigns to "-Loans"; the true FY26 value for this line is
    # 20,181, which the engine hands to "Income taoc assets" instead. One
    # wrong period poisons the caption, so both are forfeited.
    "-Other ffinancral' assets",
    # "-other financial: assets" (current other financial assets, 267,662 /
    # 244,264) is sent to intangible_assets at medium confidence, where it
    # would publish as intangibles while the printed "Other intangible
    # assets" (1,332,569 / 1,252,604, statically mapped) sits refused in the
    # same no-half bucket beside two more engine suggestions of the same
    # kind. Other financial assets are not intangibles; withdrawn so the
    # completed intangibles take their key alone.
    "-other financial: assets",
    # "Income taoc assets (net}" pairs OFA's 20,181 as its FY26 cell (the
    # same one-cell shift); the printed FY26 income-tax asset is part of the
    # mangled 191,413 that also holds deferred tax assets, and the split is
    # not recoverable from this extraction. FY25=24,978 is correct and is
    # forfeited with the caption: one true and one false period under one
    # key is worse than a recorded shortfall.
    "Income taoc assets (net}",
    # "other current assets" prints 125,718 for FY26 -- the current-assets
    # subtotal 902,154 closes exactly with it (6,009 + 137,006 + 5,040 +
    # 79,776 + 137,222 + 166,546 + 244,264 + 125,718 + 573) -- but the
    # extraction reads 1,125,718, a spurious leading digit, and the caption
    # maps at HIGH confidence, so the nine-times-overstated figure would
    # publish. FY25=144,608 is correct and forfeited with it.
    "other current assets",
    # "-Other financial liabilities" (current, 408,659 / 333,024) is a
    # distinct printed line the engine sends to other_current_liabilities,
    # where the exact-name static line "Other current liabilities"
    # (77,341 / 77,522) already sits: one key, two lines, and the twin gate
    # refuses both. The caption that names what the key is keeps it; the
    # damaged sibling withdraws so it publishes. The non-current sibling
    # "-other financial lfabilities" (26,320 / 38,642) has no key at all
    # and stays queued unmapped.
    "-Other financial liabilities",
    # "Equity attributable to owners of the parent" (1,490,566 / 1,136,719)
    # is the parent-only rupee subtotal, and the engine sends it to
    # share_count at medium confidence -- the same suggestion that put
    # rupees in a share-count key on TCS's face, where the guard declines
    # it and the withdrawal made the refusal structural. Same caption
    # class, same treatment: the printed total equity beside it
    # (1,959,634 / 1,534,677) holds the whole figure.
    "Equity attributable to owners of the parent",
    # --- Larsen & Toubro audited consolidated face (printed 617-618) ---
    #
    # The FY26 integrated report's balance sheet spans two printed pages, and
    # every refusal below is decided against the figures the pages state: both
    # halves foot exactly in both periods -- non-current assets 134,238.56,
    # current assets 292,841.13, non-current liabilities 69,521.91, current
    # liabilities 233,531.47, closing on a total of 452,549.88 at FY26 -- so
    # each figure quoted here is the printed one.
    #
    # "Deferred tax liabilities (net) 51(d)": the filer's note reference
    # extracts into the caption, so the clean string's earlier withdrawal
    # misses this variant, and the engine sends the liability to
    # deferred_tax_assets at medium confidence where the true tax assets
    # (3,792.88 / 4,252.76, printed non-current) already sit. It would
    # publish 410.01 / 167.11 as assets beside them. A liability is not an
    # asset; withdrawn.
    "Deferred tax liabilities (net) 51(d)",
    # The three "Sub-total" captions are the page's own section totals, and
    # the engine sends each to the detail key that its section's exact-name
    # line already takes, at medium confidence: 233,531.47 beside "Other
    # current liabilities" (63,326.97 / 85,861.52), 134,238.56 beside
    # "Other non-current assets" (2,659.78 / 2,699.49), 69,521.91 beside
    # "Other non-current liabilities" (594.74 / 36.82). One key, two lines,
    # and the twin gate refuses both, so today all six real lines publish
    # nothing. A sub-total is not the line it totals; withdrawn so the
    # exact-name captions take their keys alone. "Sub-total - Current
    # assets" reaches its own key (total_current_assets) with no rival and
    # stays mapped.
    "Sub-total - Current liabilities",
    "Sub-total - Non-current assets",
    "Sub-total - Non-current liabilities",
    # "Due to micro enterprises and small enterprises" is one of the two
    # parts L&T prints trade payables in (1,840.35 + 67,615.28 = 69,455.63
    # at FY26; "Due to others" is the other part and has no key). The engine
    # sends the slice to trade_payables at medium confidence, and the
    # selector prefers filing rows, so the whole line would read 1,840.35
    # -- a thirty-eight-fold understatement published under a caption that
    # states no sum. No printed caption states the whole; withdrawn so the
    # confirmed feed figure keeps the key and both parts stay recorded.
    "Due to micro enterprises and small enterprises",
})

# Mapping entry type: (canonical_key, statement)
RAW_METRIC_MAP: Dict[str, Tuple[str, str]] = {
    # --- Income Statement ---
    "Revenues": ("canonical.is.revenue", "is"),
    "Sales": ("canonical.is.revenue", "is"),
    "Cost of sales": ("canonical.is.cost_of_sales", "is"),
    "Raw Material Cost": ("canonical.is.cost_of_sales", "is"),
    "Gross profit": ("canonical.is.gross_profit", "is"),
    "Research and development": ("canonical.is.research_development", "is"),
    "Selling and admin": ("canonical.is.selling_admin_exp", "is"),
    "Selling and marketing": ("canonical.is.sales_marketing", "is"),
    "General and administrative": ("canonical.is.general_admin", "is"),
    # NOT "Administrative expenses": the filing prints no selling line beside
    # it, and the derivation just below refuses to build the combined total
    # from one half -- publishing the admin half under a selling-and-admin
    # label states a number the filer never reported. Withdrawn below.
    "Employee Cost": ("canonical.is.employee_cost", "is"),
    "Other Mfr. Exp": ("canonical.is.other_mfr_exp", "is"),
    "Power and Fuel": ("canonical.is.power_fuel", "is"),
    "Other Expenses": ("canonical.is.other_exp", "is"),
    "Total operating expenses": ("canonical.is.total_opex", "is"),
    "Operating profit": ("canonical.is.operating_profit", "is"),
    "Depreciation": ("canonical.is.depreciation_amortization", "is"),
    "Depreciation and amortization": ("canonical.is.depreciation_amortization", "is"),
    "Finance cost": ("canonical.is.finance_cost", "is"),
    "Interest": ("canonical.is.finance_cost", "is"),
    "Other Income": ("canonical.is.other_income", "is"),
    "Other income, net": ("canonical.is.other_income", "is"),
    "Interest receivable on income tax refund": ("canonical.is.other_income", "is"),
    "Profit before tax": ("canonical.is.pbt", "is"),
    "Profit before income taxes": ("canonical.is.pbt", "is"),
    "Tax": ("canonical.is.tax", "is"),
    "Income tax expense": ("canonical.is.tax", "is"),
    "Net Profit": ("canonical.is.net_profit", "is"),
    "Net profit": ("canonical.is.net_profit", "is"),
    "Owners of the Company": ("canonical.is.net_profit", "is"),
    "Non-controlling interests": ("canonical.is.non_controlling_interests", "is"),
    "Basic (₹)": ("canonical.is.eps_basic", "is"),
    "Basic (in shares) 2.13 4,046,019,309": ("canonical.is.eps_basic", "is"),
    "Basic (in Rs)": ("canonical.is.eps_basic", "is"),
    # The SEC ingestion emits these for a US filer, in dollars per share. Without
    # them the diluted share count cannot be derived from the filed figures and
    # falls through to the live provider, which is where NVIDIA's 24,147m came from
    # while its filing carried 24,304m shares outstanding.
    "Basic (in $)": ("canonical.is.eps_basic", "is"),
    "Diluted (in $)": ("canonical.is.eps_diluted", "is"),
    "Diluted (₹)": ("canonical.is.eps_diluted", "is"),
    "Diluted (in Rs)": ("canonical.is.eps_diluted", "is"),
    "EPS in Rs": ("canonical.is.eps_diluted", "is"),
    "EPS in Rs.": ("canonical.is.eps_diluted", "is"),

    # --- Balance Sheet (Assets) ---
    "Net Block": ("canonical.bs.ppe", "bs"),
    # TCS prints the words, not the block label: "Property, plant and equipment"
    # 11,032 / 10,978 on its consolidated face (p.11; p.20 is the standalone
    # face and is not read). Same line the key is named for.
    "Property, plant and equipment": ("canonical.bs.ppe", "bs"),
    # Gross asset base and accumulated depreciation. Both are needed to measure the
    # depreciation rate the steady-state capex target is built on; see
    # backend/forecast/assumptions.py.
    "Gross Block": ("canonical.bs.ppe_gross", "bs"),
    "Accumulated Depreciation": ("canonical.bs.accumulated_depreciation", "bs"),
    "Capital Work in Progress": ("canonical.bs.cwip", "bs"),
    "Goodwill": ("canonical.bs.goodwill", "bs"),
    "Intangible assets": ("canonical.bs.intangible_assets", "bs"),
    # TCS splits Goodwill / Other intangible assets (176 / 940); the
    # ex-goodwill bucket is what this key holds.
    "Other intangible assets": ("canonical.bs.intangible_assets", "bs"),
    "Non-current investments": ("canonical.bs.non_current_investments", "bs"),
    "Deferred income tax assets": ("canonical.bs.deferred_tax_assets", "bs"),
    # TCS words it "Deferred tax assets (net)" (4,465 / 3,578, non-current
    # only): same line, shorter caption.
    "Deferred tax assets (net)": ("canonical.bs.deferred_tax_assets", "bs"),
    "Income tax assets": ("canonical.bs.income_tax_assets", "bs"),
    # TCS prints it in both halves (1,439 non-current / 1,259 current at FY26);
    # `_key_for_half` routes the current rows to current_income_tax_assets,
    # the same split that resolved Infosys' two-sided caption.
    "Income tax assets (net)": ("canonical.bs.income_tax_assets", "bs"),
    "Other non-current assets": ("canonical.bs.other_non_current_assets", "bs"),
    "Total non-current assets": ("canonical.bs.total_non_current_assets", "bs"),
    "Current investments": ("canonical.bs.current_investments", "bs"),
    # NOT "Investments", for the same reason as "Other Assets" above: Screener's
    # Data Sheet prints an aggregate, not the filer's caption.
    #
    # Infosys' own balance sheet separates them -- "Current investments 12,950" and
    # "Non-current investments 8,930" -- and Screener collapses both into one
    # "Investments" row reading 21,880. Mapped to the CURRENT line that is the
    # whole total, and `Non-current investments` is read separately, so the money is
    # counted twice:
    #
    #     FY24  12,915 current + 11,708 non-current = 24,623  published as current
    #     FY25  12,482 current + 11,059 non-current = 23,541  published as current
    #     FY26  12,950 current +  8,930 non-current = 21,880  published as current
    #
    # Exact to the rupee in all three years, which is what identifies it: the
    # published current figure equals current PLUS non-current precisely.
    #
    # The honest position is the one taken for "Other Assets": the engine does not
    # know how much of that total is current, so it does not claim to. An
    # under-count is visible and checkable, and `current_assets_reconcile` reports
    # the shortfall. An over-count wearing a filed caption's name is neither.
    #
    # A filer that prints a line genuinely captioned "Current investments" reaches
    # this key through that caption, below.
    "Current investments": ("canonical.bs.current_investments", "bs"),
    "- Certificates of deposit": ("canonical.bs.current_investments", "bs"),
    "- Commercial paper": ("canonical.bs.current_investments", "bs"),
    "- Mutual fund units": ("canonical.bs.current_investments", "bs"),
    "- Other investments": ("canonical.bs.current_investments", "bs"),
    "- Quoted debt securities": ("canonical.bs.current_investments", "bs"),
    "- Target maturity funds units": ("canonical.bs.current_investments", "bs"),
    "Vendor non-trade receivables": ("canonical.bs.vendor_non_trade_receivables", "bs"),
    "Receivables": ("canonical.bs.trade_receivables", "bs"),
    "Trade receivables": ("canonical.bs.trade_receivables", "bs"),
    "Trade receivables and unbilled revenue": ("canonical.bs.trade_receivables", "bs"),
    "Unbilled revenue": ("canonical.bs.unbilled_revenue", "bs"),
    # TCS prints the bare word in both halves (114 non-current / 10,084
    # current at FY26). The half guard declines the non-current row for lack
    # of a key, so the current figure publishes and nothing is misfiled.
    "Unbilled": ("canonical.bs.unbilled_revenue", "bs"),
    "Inventory": ("canonical.bs.inventory", "bs"),
    "Cash & Bank": ("canonical.bs.cash_and_bank", "bs"),
    "Cash and cash equivalents": ("canonical.bs.cash_and_bank", "bs"),
    "Prepayments and other assets": ("canonical.bs.prepayments_other_current_assets", "bs"),
    # The filer's own caption. Screener and the PDF reader print different words for
    # the same line, and only one of them was listed, so Infosys' balance sheet lost
    # the line entirely: it prints "Prepayments and other current assets 15,703" and
    # that label matched nothing, leaving the key to be filled by the cash-flow
    # statement's "Prepayments and other assets (2,312)".
    #
    # With both captions present the filed figure wins and the movement is refused
    # for being a cash-flow caption (see mapper._statement_agrees).
    "Prepayments and other current assets": ("canonical.bs.prepayments_other_current_assets", "bs"),
    # NOT "Other Assets". Screener.in's Data Sheet groups the balance sheet by
    # analysis rather than by caption, and its "Other Assets" row is a broad
    # aggregate: for Infosys at 2026-03-31 it reads 98,112 while the lines beneath
    # it on the same sheet are cash 22,201, investments 21,880 and receivables
    # 35,234, so it already contains them. Mapped to the narrow current-asset
    # catch-all it made the itemised block sum to 192,910 against a filed
    # current-asset subtotal of 103,489, and the engine published a balance sheet
    # that nearly doubled the filer's own total.
    #
    # The honest position is that the engine does not know what that money is. An
    # under-count is visible and checkable; an over-count dressed as a named line is
    # neither, and `current_assets_reconcile` now reports the shortfall rather than
    # leaving it to be found by a reader.
    #
    # A filer whose own balance sheet prints a line captioned "Other Assets" is a
    # different thing, and reaches the same key through that filer's own caption
    # list rather than through this aggregator.
    #
    # NOT "Cash flow hedge reserves": a component parked on a total key. The
    # reported boost would otherwise publish the hedge component (6 at FY24)
    # as total other reserves (86,045). Withdrawn below; the aggregate the
    # screener prints keeps publishing as today.
    "Current income tax assets": ("canonical.bs.current_income_tax_assets", "bs"),
    "Current derivative financial assets": ("canonical.bs.derivative_financial_assets_current", "bs"),
    # The filer's own caption. Infosys prints "Derivative financial instruments" on
    # both sides of its balance sheet -- 83 in current assets and 593 in current
    # liabilities -- without the word "current" on the asset side. Without this the
    # 83 did not reach the reconciliation at all, leaving it short by exactly that.
    "Derivative financial instruments": ("canonical.bs.derivative_financial_assets_current", "bs"),
    "Total current assets": ("canonical.bs.total_current_assets", "bs"),
    "Total assets": ("canonical.bs.total_assets", "bs"),
    "Total Assets": ("canonical.bs.total_assets", "bs"),
    "Total_Asset": ("canonical.bs.total_assets", "bs"),
    # TCS prints the subtotal in full capitals (182,372 = total equity and
    # liabilities to the rupee, verified against the same page).
    "TOTAL ASSETS": ("canonical.bs.total_assets", "bs"),

    # --- Balance Sheet (Liabilities & Equity) ---
    "Equity Share Capital": ("canonical.bs.equity_capital", "bs"),
    # TCS prints "Share capital" 362 both years on its consolidated face; the
    # registry comment above foresaw exactly this caption beside Other equity.
    "Share capital": ("canonical.bs.equity_capital", "bs"),
    "Retained earnings": ("canonical.bs.retained_earnings", "bs"),
    "Reserves": ("canonical.bs.other_reserves", "bs"),
    "Other reserves": ("canonical.bs.other_reserves", "bs"),
    "Capital redemption reserve": ("canonical.bs.other_reserves", "bs"),
    "Total equity": ("canonical.bs.total_equity", "bs"),
    "Borrowings": ("canonical.bs.borrowings", "bs"),
    "Short term borrowings": ("canonical.bs.short_term_borrowings", "bs"),
    "Finance lease liabilities": ("canonical.bs.finance_lease_liabilities", "bs"),
    "Operating lease liabilities": ("canonical.bs.operating_lease_liabilities", "bs"),
    "Mezzanine equity": ("canonical.bs.mezzanine_equity", "bs"),
    "Total mezzanine equity": ("canonical.bs.mezzanine_equity", "bs"),
    "Mezzanine": ("canonical.bs.mezzanine_equity", "bs"),
    "Redeemable noncontrolling interest": ("canonical.bs.mezzanine_equity", "bs"),
    "Minority interest": ("canonical.bs.minority_interest", "bs"),
    "Non-controlling interests": ("canonical.bs.minority_interest", "bs"),
    "Non-controlling interest": ("canonical.bs.minority_interest", "bs"),
    "Preference share capital": ("canonical.bs.preferred_stock", "bs"),
    "Preferred stock": ("canonical.bs.preferred_stock", "bs"),
    "Trade payables": ("canonical.bs.trade_payables", "bs"),
    "Unearned revenue": ("canonical.bs.unearned_revenue", "bs"),
    "Lease liabilities": ("canonical.bs.lease_liabilities", "bs"),
    "Other current liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    "Other Liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    # TCS prints it lowercase, current half only (6,866 / 7,188): one figure,
    # so the case variant is safe where the two-figure captions below are not.
    "Other liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    "Other non-current liabilities": ("canonical.bs.other_non_current_liabilities", "bs"),
    "Other liabilities and provisions": ("canonical.bs.other_non_current_liabilities", "bs"),
    "Provision for post sale client support and other provisions": ("canonical.bs.provisions", "bs"),
    "Provisions": ("canonical.bs.provisions", "bs"),
    "Billed": ("canonical.bs.trade_receivables", "bs"),
    "Inventories": ("canonical.bs.inventory", "bs"),
    "Capital work-in-progress": ("canonical.bs.cwip", "bs"),
    "Class B compulsorily convertible preference shares": ("canonical.bs.preferred_stock", "bs"),
    "Dues of creditors other than small enterprises and micro enterprises": ("canonical.bs.trade_payables", "bs"),
    "Dues of small enterprises and micro enterprises": ("canonical.bs.trade_payables", "bs"),
    "Other balances with banks": ("canonical.bs.cash_and_bank", "bs"),
    "Investments accounted for using the equity method": ("canonical.bs.non_current_investments", "bs"),
    "Total current liabilities": ("canonical.bs.total_current_liabilities", "bs"),
    "Total non-current liabilities": ("canonical.bs.total_non_current_liabilities", "bs"),
    "Total liabilities": ("canonical.bs.total_liabilities", "bs"),
    "Total liabilities and equity": ("canonical.bs.total_liabilities_and_equity", "bs"),
    "Total Liabilities & Equity": ("canonical.bs.total_liabilities_and_equity", "bs"),
    "Total_Liab": ("canonical.bs.total_liabilities", "bs"),
    # TCS prints it in full capitals; same verified footing as TOTAL ASSETS.
    "TOTAL EQUITY AND LIABILITIES": ("canonical.bs.total_liabilities_and_equity", "bs"),

    # --- Balance Sheet, HCLTech audited Ind-AS face (printed page 4) ---
    #
    # The filer's own captions, prefix and all: Ind AS letters each component
    # ("(a) Property, plant and equipment"), and stripping the letters would
    # fuse captions this page prints as different lines. Every caption on this
    # page that is refused is in WITHDRAWN_LABELS above with its reason.
    #
    # Non-current assets.
    "(a) Property, plant and equipment": ("canonical.bs.ppe", "bs"),
    "(b) Capital work in progress": ("canonical.bs.cwip", "bs"),
    "(d) Goodwill": ("canonical.bs.goodwill", "bs"),
    "(e) Other intangible assets": ("canonical.bs.intangible_assets", "bs"),
    # Printed in BOTH halves: 130 non-current and 6,960 current at FY26. The
    # registry gives the non-current key, which is where the non-current row
    # belongs, and `_key_for_half` routes the current row to
    # `current_investments` -- the two lines the filing's own half structure
    # separates.
    "(i) Investments": ("canonical.bs.non_current_investments", "bs"),
    # Printed only under non-current assets (601 / 1,022). The half guard
    # declines it for the same reason it declines TCS's non-current "Unbilled":
    # the unbilled key is a current-asset line and this figure is not current.
    # A recorded shortfall, not a mapping error.
    "(ii) Trade receivables -unbilled": ("canonical.bs.unbilled_revenue", "bs"),
    "(h) Deferred tax assets (net)": ("canonical.bs.deferred_tax_assets", "bs"),
    # The face's table font breaks the ToUnicode map on three captions: the
    # hyphenated "non-current" extracts as "non..:urrent" and "Non-controlling"
    # as "Non..:ontrolling", so those are the strings the reader receives.
    # The figures beside them read clean (total non-current assets 45,716,
    # footing the page), and mapping the extracted string is the only way the
    # printed lines reach their keys -- a prettier caption would never match.
    "(i) Other non..:urrent assets": ("canonical.bs.other_non_current_assets", "bs"),
    "Total non..:urrent assets": ("canonical.bs.total_non_current_assets", "bs"),
    "Non..:ontrolling interest": ("canonical.bs.minority_interest", "bs"),
    # Current assets.
    "(a) Inventories": ("canonical.bs.inventory", "bs"),
    "(iii) Cash and cash equivalents": ("canonical.bs.cash_and_bank", "bs"),
    "(c) Current tax assets (net)": ("canonical.bs.current_income_tax_assets", "bs"),
    "(d ) Other current assets": ("canonical.bs.prepayments_other_current_assets", "bs"),
    # Equity and liabilities.
    "(a ) Equity share capital": ("canonical.bs.equity_capital", "bs"),
    "TOTAL EQUITY": ("canonical.bs.total_equity", "bs"),
    "TOTAL LIABILITIES": ("canonical.bs.total_liabilities", "bs"),
    "(e ) Other non-current liabilities": ("canonical.bs.other_non_current_liabilities", "bs"),
    "(c) Other current liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    # The current block's provisions (1,664 / 1,487). Its non-current twin
    # "(c) Provisions" is withdrawn above because the only provisions key is
    # this block's line.
    "(d ) Provisions": ("canonical.bs.provisions", "bs"),

    # --- Balance Sheet, Reliance audited consolidated face (printed page 16) ---
    #
    # Title case throughout, so these spellings are pinned statically rather than
    # left to the engine's fuzzy suggestions: the dry run published an 83,453
    # liability as a deferred-tax asset and an 829,668 equity component as the
    # equity total on medium suggestions, and static entries make those outcomes
    # impossible. Every caption this page prints that is refused is in
    # WITHDRAWN_LABELS above with its reason. Only the FY25 column reads cleanly
    # (the FY26 column's header extracts as nothing and its cells come out
    # missing, garbled, or wrong); the metadata records FY25 only.
    #
    # Non-current assets. The "Olher ..." captions keep the extracted spelling:
    # the face's font drops the "t" the way HCLTech's breaks "non-current", and
    # a prettier caption would never match what the reader receives.
    "Property, Plant and Equipment": ("canonical.bs.ppe", "bs"),
    "Capital Work-in-Progress": ("canonical.bs.cwip", "bs"),
    "Olher Intangible Assets": ("canonical.bs.intangible_assets", "bs"),
    "Deferred Tax Assets (Net)": ("canonical.bs.deferred_tax_assets", "bs"),
    "Olher Non-Current Assets": ("canonical.bs.other_non_current_assets", "bs"),
    "Total Non-Current Assets": ("canonical.bs.total_non_current_assets", "bs"),
    # Current assets.
    "Cash and Cash Equivalents": ("canonical.bs.cash_and_bank", "bs"),
    "Other Current Assets": ("canonical.bs.prepayments_other_current_assets", "bs"),
    "Total Current Assets": ("canonical.bs.total_current_assets", "bs"),
    # Equity and liabilities. "Total Equi and Liabilities" is the printed typo
    # for the total every other face spells out; it foots the page (1,950,121),
    # so the extracted string is what the registry keeps.
    "Non-Controlling Interest": ("canonical.bs.minority_interest", "bs"),
    "Total Equity": ("canonical.bs.total_equity", "bs"),
    "Total Liabilities": ("canonical.bs.total_liabilities", "bs"),
    "Total Non-Current Liabilities": ("canonical.bs.total_non_current_liabilities", "bs"),
    "Total Current Liabilities": ("canonical.bs.total_current_liabilities", "bs"),
    "Total Equi and Liabilities": ("canonical.bs.total_liabilities_and_equity", "bs"),
    "Other Current Liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    "Other Non-Current Liabilities": ("canonical.bs.other_non_current_liabilities", "bs"),
    # "Lease Liabilities" prints in both blocks (17,142 non-current, 4,903
    # current) under one caption with no half-specific keys to split it to.
    # The twin gate refuses both printings and queues them; the static entry
    # records the caption's key all the same, so a future split has a decision
    # to attach to rather than an unmapped gap.
    "Lease Liabilities": ("canonical.bs.lease_liabilities", "bs"),
    "Trade Payables": ("canonical.bs.trade_payables", "bs"),
    "Trade Receivables": ("canonical.bs.trade_receivables", "bs"),
    # --- Balance Sheet, ONGC audited consolidated face (printed p.35 + p.36) ---
    #
    # ONGC numbers every block ("(1) Non-current assets", "(2) Current assets"), which
    # the half reader now tolerates, so the rows carry their half and the half-routed
    # keys resolve by position rather than by a static entry's guess. What is pinned
    # statically here is what the ENGINE gets wrong on this face, decided against the
    # figures the filing prints.
    #
    # The two tax lines are the same class as Reliance's: the engine put a 38,765
    # deferred-tax LIABILITY on `deferred_tax_assets` and a 642 current tax LIABILITY on
    # `current_income_tax_assets`, inverting the statement and refusing the true 7,081
    # and 2.81 assets beside them. Both liabilities are withdrawn above; the two assets
    # take the keys below.
    "(i) Deferred tax assets (net)": ("canonical.bs.deferred_tax_assets", "bs"),
    "(c) Current Tax Assets (net)": ("canonical.bs.current_income_tax_assets", "bs"),
    # "(j) Non-current tax assets (net)" (14,674 / 15,563) is income tax, not deferred
    # tax: the engine suggested the deferred-tax key at medium confidence, which is what
    # put it in the same refusal bucket as the true deferred-tax asset beside it. The
    # non-current income-tax key exists and is what this line is.
    "(j) Non-current tax assets (net)": ("canonical.bs.income_tax_assets", "bs"),
    "(a) Equity share capital": ("canonical.bs.equity_capital", "bs"),
    # "(g) Investments in Joint Ventures and Associates" (58,647 / 63,753) is the
    # non-current investments line. Its non-current sibling "(i) Other Investments"
    # (33,717 / 34,224) is withdrawn above: one key cannot hold both and the face prints
    # no subtotal for the block.
    "(g) Investments in Joint Ventures and Associates": ("canonical.bs.non_current_investments", "bs"),
    # "(ii) Lease Liabilities" prints in both halves (9,877 non-current, 24,384
    # current) under one caption with no half-specific keys to split it to, so the twin
    # gate refuses both printings. The entry records the caption's key so a future split
    # has a decision to attach to.
    "(ii) Lease Liabilities": ("canonical.bs.lease_liabilities", "bs"),
    "(b) Provisions": ("canonical.bs.provisions", "bs"),
    "(d) Goodwill (including Goodwill on Consolidation)": ("canonical.bs.goodwill", "bs"),
    "(b) Other current liabilities": ("canonical.bs.other_current_liabilities", "bs"),
    "(d) Other non-current liabilities": ("canonical.bs.other_non_current_liabilities", "bs"),
    "(k) Other non-current assets": ("canonical.bs.other_non_current_assets", "bs"),
    "(d) Other current assets": ("canonical.bs.prepayments_other_current_assets", "bs"),
    "Total equity and liabilities": ("canonical.bs.total_liabilities_and_equity", "bs"),
    # --- Balance Sheet, Tata Steel audited consolidated face (printed p.20) ---
    #
    # "TOTAL-ASSETS" is the letter-spaced "T O T A L - A S SE T S" once the
    # spacing is gone: the words name the line and the figure closes both sides
    # of the sheet (279,394.80 at FY25; 301,254.11 at FY26, over the 255.06
    # held-for-sale bridge exactly as ONGC's face does). The engine reads the
    # hyphenated form at low confidence, so without this entry the footing line
    # would not publish at all.
    "TOTAL-ASSETS": ("canonical.bs.total_assets", "bs"),
    # The engine sends this home at high confidence and the footing proves it:
    # the figure equals TOTAL-ASSETS on both periods.
    "TOTAL - EQUITY AND LIABILITIES": ("canonical.bs.total_liabilities_and_equity", "bs"),
    # The current tax asset printed in the current block (79.52 / 76.28), the
    # same family as ONGC's "(c) Current Tax Assets (net)": the caption states
    # what it is, and no sibling tax line competes for the key on this face.
    "(d) Current tax assets": ("canonical.bs.current_income_tax_assets", "bs"),

    # --- Balance Sheet, Wipro audited consolidated face (printed p.21) ---
    #
    # "lnvcstmcnts" is the printed "Investments" of the current block, carrying
    # the same glyph damage that turns this page's thousands separators into
    # periods: the non-current sibling extracts as the clean "Investments"
    # (withdrawn globally against the screener aggregate), and this one sits
    # under "Curr('nt assets" -> "Financial assets" with 411,474 / 437,680
    # million. The block foots only with it: the parsed current assets plus
    # the one refused cash cell sum to the printed totals exactly, 777,775 at
    # FY25 and 826,354 at FY26. The engine has no stem to match (0.2), so
    # without this entry the filing states its own treasury line and the model
    # reads the aggregator instead.
    "lnvcstmcnts": ("canonical.bs.current_investments", "bs"),

    # --- Balance Sheet, Sun Pharmaceutical audited consolidated face (printed p.19) ---
    #
    # This face prints every caption in full; what is pinned here is what the
    # ENGINE gets wrong or misses on it, decided against the figures the page
    # prints.
    #
    # The two tax assets, same class as ONGC's: the engine sends "(g) Deferred
    # tax assets (Net)" home correctly but sends "(h) Income tax assets (Net)"
    # (4,206.7 / 6,451.3) to the deferred-tax key at medium confidence, which
    # is what would put it in the same refusal bucket as the true deferred-tax
    # asset beside it (44,075.5 / 40,464.6). Income tax is not deferred tax;
    # the non-current income-tax key is what that line is, and with the
    # liability captions withdrawn above each asset takes one key alone.
    "(g) Deferred tax assets (Net)": ("canonical.bs.deferred_tax_assets", "bs"),
    "(h) Income tax assets (Net)": ("canonical.bs.income_tax_assets", "bs"),
    # "(c) Goodwill (Net)" (89,394.2 / 98,330.8): the engine has no stem to
    # match on the parenthesised form (0.2), and the key already holds this
    # line for every other face that prints it.
    "(c) Goodwill (Net)": ("canonical.bs.goodwill", "bs"),
    # "(d) Other intangible assets" (36,109.2 / 118,750.8): the completed
    # intangibles, the same caption TCS and Reliance print under their own
    # lettering. Its under-development sibling is withdrawn above so the pair
    # cannot refuse each other on the one key.
    "(d) Other intangible assets": ("canonical.bs.intangible_assets", "bs"),

    # --- Balance Sheet, Bharti Airtel audited consolidated face (printed p.3) ---
    #
    # Captions whose extraction is damaged but whose FIGURES are witnessed
    # against the page's own subtotals, so each entry pins the line the page
    # prints rather than the glyphs the engine reads.
    #
    # "Other mon-cwrrent assets" (FY26=124,770): the non-current assets
    # subtotal 4,619,362 closes exactly over the clean lines plus this
    # figure plus the 191,413 mangled tax-assets token, so the value is the
    # printed one even though the caption is not. FY25 ("H6,6,38") did not
    # extract and is forfeited. The engine sends the damaged caption to
    # intangible_assets at medium confidence; the key here is the line it
    # names, and it clears the intangibles bucket the withdrawals above
    # emptied.
    "Other mon-cwrrent assets": ("canonical.bs.other_non_current_assets", "bs"),
    # "Total rrabi6ties" (3,561,882 / 3,608,927): the engine has no stem to
    # match on the damaged glyphs (0.2), and the figures foot exactly as the
    # page's own liability subtotals -- 1,816,825 + 1,745,057 at FY26,
    # 1,804,525 + 1,804,402 at FY25. Same line every face prints.
    "Total rrabi6ties": ("canonical.bs.total_liabilities", "bs"),
    # "-Iiavestments" is the CURRENT investments line (137,006 / 16,532;
    # the "I" for "l" is the damage), and the non-current sibling extracts
    # clean as "-Investments" (11,385 / 5,435) and reaches
    # non_current_investments through the engine. Routed to the current key
    # directly, the way Wipro's "lnvcstmcnts" was: the FY25 row carries no
    # half claim, and routing it through the non-current key would put
    # 16,532 beside the clean 5,435 in one no-half bucket and refuse both
    # investments lines.
    "-Iiavestments": ("canonical.bs.current_investments", "bs"),

    # --- Cash Flow Statement ---
    "Cash from Operating Activity": ("canonical.cf.operating_activities", "cf"),
    "Income taxes paid": ("canonical.cf.taxes_paid", "cf"),
    "Cash from Investing Activity": ("canonical.cf.investing_activities", "cf"),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("canonical.cf.capex", "cf"),
    "PaymentsToAcquireProductiveAssets": ("canonical.cf.capex", "cf"),
    "Capital Expenditure": ("canonical.cf.capex", "cf"),
    "Purchase of Property, Plant and Equipment": ("canonical.cf.capex", "cf"),
    "Fixed Assets Purchased": ("canonical.cf.capex", "cf"),
    "Payment for acquisition of business, net of cash acquired": ("canonical.cf.business_acquisitions", "cf"),
    "Interest and dividend received": ("canonical.cf.interest_div_received", "cf"),
    "Cash from Financing Activity": ("canonical.cf.financing_activities", "cf"),
    "Dividend Amount": ("canonical.cf.dividends_paid", "cf"),
    # The filing's own caption, read from the financing section on the continuation
    # page of both Infosys documents (printed 105 under 104, printed 111 under 110):
    # (14,692) FY24, (20,287) FY25, (18,653) FY26. The key was empty for this
    # company until now -- the aggregator's "Dividend Amount" rows are refused by
    # the statement guard, so the model's dividends line fell back to whatever the
    # forecast assumed. The dividends-to-minority line printed beside it is
    # withdrawn (see WITHDRAWN_LABELS) so the key carries one figure per period
    # rather than two rivals the selector would order arbitrarily.
    "Payment of dividends": ("canonical.cf.dividends_paid", "cf"),
    "Other adjustments": ("canonical.cf.other_adjustments", "cf"),
    "Stock compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Stock Based Compensation": ("canonical.cf.stock_compensation", "cf"),
    "Share Based Compensation": ("canonical.cf.stock_compensation", "cf"),
    "Share-based compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Stock-based compensation expense": ("canonical.cf.stock_compensation", "cf"),
    "Net Cash Flow": ("canonical.cf.net_change_in_cash", "cf"),
    # The filing prints its own section totals on the statement page, and the
    # confidence engine sends three of the four captions to net_change_in_cash,
    # where a section total would rival the actual bottom line -- the operating
    # one wins it, 35,824 at FY26 against the reported net change. Mapped to
    # their own sections the statement adds up, which is the relationship the
    # model derives the bottom line from: the three filed sections sum to the
    # filing's own printed net-increase caption exactly, (3,854) at FY26,
    # 9,587 at FY25 and 2,697 at FY24, each verified against the documents
    # (operating + investing + financing, and the captions carry one figure per
    # period).
    "Net cash generated by operating activities": ("canonical.cf.operating_activities", "cf"),
    "Net cash generated/(used) in investing activities": ("canonical.cf.investing_activities", "cf"),
    "Net cash generated from investing activities": ("canonical.cf.investing_activities", "cf"),
    "Net cash used in financing activities": ("canonical.cf.financing_activities", "cf"),
    # The filing's printed bottom line, on the continuation page under the three
    # sections. It disagrees with the aggregator's "Net Cash Flow" ((3,854)
    # against (2,254) at FY26) because the aggregator's figure folds in the
    # exchange effect the filing prints on its own line, (1,600) at FY26: the
    # roll-forward closes either way, 24,455 + (3,854) + 1,600 = 22,201. The
    # model publishes the sum of the three sections for this line, so choosing
    # the filing's caption keeps the reported figure identical to that sum
    # instead of logging a disagreement on every rebuild.
    "Net increase/(decrease) in cash and cash equivalents": ("canonical.cf.net_change_in_cash", "cf"),
    # The filing's own exchange line, on the continuation page under the three
    # sections (printed 105 under 104, printed 111 under 110): (84) FY24,
    # 82 FY25, 1,600 FY26. The three sections sum to the printed bottom line
    # exactly, so this row sits OUTSIDE them as a memo, and the reconciliation
    # check absorbs it: 2,697 + (84) = 2,613 at FY24, 9,587 + 82 = 9,669 at
    # FY25, (3,854) + 1,600 = (2,254) at FY26, each closing to the rupee.
    # Distinct by value and page from the two withdrawn fx captions --
    # "Exchange differences on translation of assets and liabilities, net"
    # (76 / 79 / 954, an operating-section line) and "Exchange differences on
    # translation of foreign operations" (226 / 357 / 3,256, OCI) -- so neither
    # withdrawal is touched. Printed by Infosys only.
    "Effect of exchange rate changes on cash and cash equivalents": ("canonical.cf.fx_effect", "cf"),

    "No. of Equity Shares": ("canonical.meta.share_count", "meta"),
    "Basic (in shares)": ("canonical.meta.share_count", "meta"),
    "4,052,169,447": ("canonical.meta.share_count", "meta"),
    "Face value": ("canonical.meta.face_value", "meta"),
    "New Bonus Shares": ("canonical.meta.bonus_shares", "meta"),
    "Total Liabilities Net Minority Interest": ("canonical.bs.total_liabilities", "bs"),
    "Total Non Current Liabilities Net Minority Interest": ("canonical.bs.total_non_current_liabilities", "bs"),
}


def get_canonical_mapping(metric_raw: str) -> Tuple[str, str] | None:
    """Return (canonical_key, statement) for a raw metric label, or None if unmapped."""
    return RAW_METRIC_MAP.get(metric_raw.strip())
