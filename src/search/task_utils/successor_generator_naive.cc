#include "successor_generator_naive.h"

#include "../task_proxy.h"

using namespace std;

namespace successor_generator {
GeneratorNaive::GeneratorNaive(const TaskProxy &task_proxy) {
    for (OperatorProxy op : task_proxy.get_operators()) {
        vector<FactPair> preconditions;
        for (FactProxy precondition : op.get_preconditions())
            preconditions.push_back(precondition.get_pair()); // als (var,val) ablegen
        operators.push_back({move(preconditions), OperatorID(op.get_id())}); // Eintrag anhängen
    }
}

void GeneratorNaive::generate_applicable_ops(
    const vector<int> &state, vector<OperatorID> &applicable_ops) const {
    for (const Entry &entry : operators) {
        bool applicable = true; // annahme: anwendbar,operator ohne vorbedingung automatisch applicable
        for (const FactPair &precondition : entry.preconditions) { 
            if (state[precondition.var] != precondition.value) {
                applicable = false;
                break; // bricht die schleife ab, weil man die restliche vorbedingunen nicht anschauen muss, wenn eine nicht stimmt, ist es nicht applicable
            }
        }
        if (applicable)
            applicable_ops.push_back(entry.op);
    }
}
}
