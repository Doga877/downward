#include "successor_generator_watched_literals.h"

#include "../task_proxy.h"

using namespace std;

namespace successor_generator {
int GeneratorWatchedLiterals::find_unsatisfied_precondition(const Entry &entry, const vector<int> &state) const {    // geht alle vorbeidingugnenund gibt die positin der erte falsche --> ort der neuen watch und op anwendbar
    int num_preconditions = entry.preconditions.size();

    // VARIANTE 1 (aktiv): suche startet immer bei position 0
    for (int position = 0; position < num_preconditions; ++position) { // die position wird in watched_position gespeichert
        const FactPair &precondition = entry.preconditions[position];
        int var = precondition.var;
        int value = precondition.value;
        if (state[var] != value) { // state[var] (aktuelle Wert dieser Variable) wird mir der vorbedignugn vergleichen.
            return position;
        }
    }
    return -1; // anwendbar falls keine vorbedingungen falsch, -1 weil es nicht mit einer echte osition verwechslt werden kann.

    // VARIANTE 2 (aus): zyklische suche ab der bewachten position, diese wird uebersprungen
    // umschalten: variante 1 auskommentieren, variante 2 einkommentieren
    /*
    for (int offset = 1; offset < num_preconditions; ++offset) {
        int position = entry.watched_position + offset;
        if (position >= num_preconditions) {
            position -= num_preconditions;
        }
        const FactPair &precondition = entry.preconditions[position];
        int var = precondition.var;
        int value = precondition.value;
        if (state[var] != value) {
            return position;
        }
    }
    return -1;
    */
}

void GeneratorWatchedLiterals::start_watching(int op_id, int position) const {  // zwei verschiedene Orte im Speicher zu aktualisieren
    Entry &entry = operators[op_id];
    entry.watched_position = position; // Operator weiß, welchen Fakt er beobachtet

    const FactPair &precondition = entry.preconditions[position];
    int var = precondition.var; //  ID der Zustandsvariable
    int value = precondition.value; // konkrete Wert dieser Variable
    watchlist[var][value].push_back(op_id); // Fakt weiß, welcher Operator ihn beobachtet
}

GeneratorWatchedLiterals::GeneratorWatchedLiterals(const TaskProxy &task_proxy) {
    VariablesProxy variables = task_proxy.get_variables();
    watchlist.resize(variables.size());
    for (VariableProxy variable : variables) { // für watchlist[v][d] (Schubladen)
        int var = variable.get_id();
        int domain_size = variable.get_domain_size();
        watchlist[var].resize(domain_size); // diesem Schrank so viele Schubladen an, wie die Variable Werte hat
    }

    OperatorsProxy all_operators = task_proxy.get_operators();
    int num_operators = all_operators.size(); // anzahl der operatoren
    operators.resize(num_operators); // ein Entry pro Operator, wie bei marking

    for (OperatorProxy op : all_operators) {  // ähnlich wie bei naive,  als (var,val) ablegen
        int op_id = op.get_id();
        for (FactProxy precondition : op.get_preconditions()) {
            operators[op_id].preconditions.push_back(precondition.get_pair());
        }

        if (operators[op_id].preconditions.empty()) { // keine Vorbedingungen --> nichts beobachten --> immer applipicable
            operators_without_preconditions.push_back(OperatorID(op_id));
        } else {
            // ToDo: man kann den ersten zusatnd einfach so nehemen und einfach alles duch gehen, bis wir nicht erfüllte vorbeigung finden.
            int first_position = 0;
            start_watching(op_id, first_position);
        }
    }
}

void GeneratorWatchedLiterals::generate_applicable_ops(
    const vector<int> &state, vector<OperatorID> &applicable_ops) const {
    int num_variables = state.size();
    for (int var = 0; var < num_variables; ++var) {
        int value = state[var];
        vector<int> &watching_here = watchlist[var][value];
        woken_operators.clear();
        woken_operators.swap(watching_here);

        for (int op_id : woken_operators) { // ToDo: ich musste hier nur für die jrtzt gerade erfüllte vorbedingugn en rufen nciht für alle
            const Entry &entry = operators[op_id];
            int position = find_unsatisfied_precondition(entry, state);
            if (position == -1) { // falls outcome ist -1, dann applipicable
                watching_here.push_back(op_id); // wieso, habe ich hier nochmal gepusht
                applicable_ops.push_back(OperatorID(op_id));
            } else {
                start_watching(op_id, position);
            }
        }
    }

    for (OperatorID op : operators_without_preconditions) {
        applicable_ops.push_back(op);
    }
}
}
