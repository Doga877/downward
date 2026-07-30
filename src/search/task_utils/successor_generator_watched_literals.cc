#include "successor_generator_watched_literals.h"

#include "../task_proxy.h"

using namespace std;

namespace successor_generator {
int GeneratorWatchedLiterals::find_unsatisfied_precondition(const Entry &entry, const vector<int> &state) const {    // geht alle vorbeidingugnenund gibt die positin der erte falsche --> ort der neuen watch und op anwendbar
    int num_preconditions = entry.preconditions.size();
    for (int position = 0; position < num_preconditions; ++position) { // die position wird in watched_position gespeichert
        const FactPair &precondition = entry.preconditions[position];
        int var = precondition.var;
        int value = precondition.value;
        if (state[var] != value) { // state[var] (aktuelle Wert dieser Variable) wird mir der vorbedignugn vergleichen.
            return position;
        }
    }
    return -1; // anwendbar falls keine vorbedingungen falsch, -1 weil es nicht mit einer echte osition verwechslt werden kann.
}

void GeneratorWatchedLiterals::start_watching(int entry_id, int position) const {  // zwei verschiedene Orte im Speicher zu aktualisieren
    const Entry &entry = operators[entry_id];
    entry.watched_position = position; // Operator weiß, welchen Fakt er beobachtet

    const FactPair &precondition = entry.preconditions[position];
    int var = precondition.var; //  ID der Zustandsvariable
    int value = precondition.value; // konkrete Wert dieser Variable
    watchlist[var][value].push_back(entry_id); // Fakt weiß, welcher Operator ihn beobachtet
}

GeneratorWatchedLiterals::GeneratorWatchedLiterals(const TaskProxy &task_proxy) {
    VariablesProxy variables = task_proxy.get_variables();
    watchlist.resize(variables.size());
    for (VariableProxy variable : variables) { // für watchlist[v][d] (Schubladen)
        int var = variable.get_id();
        int domain_size = variable.get_domain_size();
        watchlist[var].resize(domain_size); // diesem Schrank so viele Schubladen an, wie die Variable Werte hat
    }

    for (OperatorProxy op : task_proxy.get_operators()) {  // ähnlich wie bei naive,  als (var,val) ablegen
        vector<FactPair> preconditions;
        for (FactProxy precondition : op.get_preconditions()) {
            preconditions.push_back(precondition.get_pair());
        }

        OperatorID op_id = OperatorID(op.get_id());
        if (preconditions.empty()) { // keine Vorbedingungen --> nichts beobachten --> immer applipiacble --> immer -1 als watched_position
            operators_without_preconditions.push_back(op_id);
        } else {
            int watched_position = -1; // ungültiger startwert (falls die schleife unten vergessen wird -> abstürtzten statt ergebnisse)
            Entry entry = {move(preconditions), op_id, watched_position};
            operators.push_back(entry);
        }
    }

    int num_entries = operators.size();
    for (int entry_id = 0; entry_id < num_entries; ++entry_id) { // jede operaot rdurch
        int first_position = 0;
        start_watching(entry_id, first_position);
    }
}

void GeneratorWatchedLiterals::generate_applicable_ops(
    const vector<int> &state, vector<OperatorID> &applicable_ops) const {
    int num_variables = state.size();
    for (int var = 0; var < num_variables; ++var) {
        int value = state[var];
        vector<int> &watching_here = watchlist[var][value];
        woken_entries.clear();
        woken_entries.swap(watching_here);

        for (int entry_id : woken_entries) {
            const Entry &entry = operators[entry_id];
            int position = find_unsatisfied_precondition(entry, state);
            if (position == -1) { // falls outcome ist -1, dann applipicable
                watching_here.push_back(entry_id);
                applicable_ops.push_back(entry.op);
            } else {
                start_watching(entry_id, position);
            }
        }
    }

    for (OperatorID op : operators_without_preconditions) {
        applicable_ops.push_back(op);
    }
}
}
