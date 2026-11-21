/**
 * @name CGA preparation extraction smoke test
 * @description Confirms that a C/C++ database contains source functions.
 * @kind problem
 * @problem.severity recommendation
 * @id local/cga-extraction-smoke
 */

import cpp

from Function function
where function.fromSource()
select function, "Extracted source function."
