/**
 * MY-IA Audit Report - Chart.js Initialization
 * Les données sont injectées via le placeholder {{CHART_DATA}}
 */

// Plugin pour afficher le texte au centre des doughnuts
const centerTextPlugin = {
    id: 'centerText',
    beforeDraw: function(chart) {
        if (chart.config.type !== 'doughnut') return;
        const ctx = chart.ctx;
        const width = chart.width;
        const height = chart.height;
        const centerX = width / 2;
        const centerY = height / 2 - 10;

        const total = chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
        const centerText = chart.options.plugins.centerText;
        if (centerText && centerText.display) {
            ctx.save();
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.font = 'bold 24px sans-serif';
            ctx.fillStyle = centerText.color || '#333';
            ctx.fillText(centerText.text || total, centerX, centerY);
            if (centerText.subtext) {
                ctx.font = '12px sans-serif';
                ctx.fillStyle = '#666';
                ctx.fillText(centerText.subtext, centerX, centerY + 20);
            }
            ctx.restore();
        }
    }
};
Chart.register(centerTextPlugin);

// Helper pour formater les labels avec pourcentage
function formatLabelWithPct(label, value, total) {
    const pct = total > 0 ? ((value / total) * 100).toFixed(0) : 0;
    return label + ' (' + pct + '%)';
}

function initCharts() {
    const data = {{CHART_DATA}};
    const totalFindings = data.severity.HIGH + data.severity.MEDIUM + data.severity.LOW;
    const totalTests = data.tests.passed + data.tests.failed + data.tests.errors + data.tests.skipped;

    // Graphique Sévérité (Doughnut)
    if (document.getElementById('severityChart')) {
        new Chart(document.getElementById('severityChart'), {
            type: 'doughnut',
            data: {
                labels: [
                    formatLabelWithPct('Critiques', data.severity.HIGH, totalFindings),
                    formatLabelWithPct('Importants', data.severity.MEDIUM, totalFindings),
                    formatLabelWithPct('Mineurs', data.severity.LOW, totalFindings)
                ],
                datasets: [{
                    data: [data.severity.HIGH, data.severity.MEDIUM, data.severity.LOW],
                    backgroundColor: ['#e74c3c', '#f39c12', '#3498db'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 10, font: { size: 11 } } },
                    centerText: { display: true, text: totalFindings, subtext: 'problèmes', color: '#333' }
                },
                cutout: '60%'
            }
        });
    }

    // Graphique Catégories (Bar horizontal)
    if (document.getElementById('categoriesChart')) {
        const catLabels = Object.keys(data.categories);
        const catValues = Object.values(data.categories);
        const catColors = ['#e74c3c', '#3498db', '#9b59b6', '#f39c12', '#27ae60'];
        new Chart(document.getElementById('categoriesChart'), {
            type: 'bar',
            data: {
                labels: catLabels,
                datasets: [{
                    data: catValues,
                    backgroundColor: catColors,
                    borderWidth: 0,
                    borderRadius: 4
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { beginAtZero: true, grid: { display: false } },
                    y: { grid: { display: false } }
                }
            }
        });
    }

    // Graphique Code vs Deps (Doughnut)
    if (document.getElementById('codeVsDepsChart')) {
        const totalCodeDeps = data.codeVsDeps.business + data.codeVsDeps.deps;
        new Chart(document.getElementById('codeVsDepsChart'), {
            type: 'doughnut',
            data: {
                labels: [
                    formatLabelWithPct('Code métier', data.codeVsDeps.business, totalCodeDeps),
                    formatLabelWithPct('Dépendances', data.codeVsDeps.deps, totalCodeDeps)
                ],
                datasets: [{
                    data: [data.codeVsDeps.business, data.codeVsDeps.deps],
                    backgroundColor: ['#6366f1', '#8b5cf6'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 10, font: { size: 11 } } },
                    centerText: { display: true, text: totalCodeDeps, subtext: 'total', color: '#6366f1' }
                },
                cutout: '60%'
            }
        });
    }

    // Graphique Évolution Historique (Line)
    if (document.getElementById('historyChart') && data.history.labels.length > 1) {
        new Chart(document.getElementById('historyChart'), {
            type: 'line',
            data: {
                labels: data.history.labels,
                datasets: [
                    {
                        label: 'Critiques (HIGH)',
                        data: data.history.high,
                        borderColor: '#e74c3c',
                        backgroundColor: 'rgba(231, 76, 60, 0.1)',
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: 'Importants (MEDIUM)',
                        data: data.history.medium,
                        borderColor: '#f39c12',
                        backgroundColor: 'rgba(243, 156, 18, 0.1)',
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: 'Mineurs (LOW)',
                        data: data.history.low,
                        borderColor: '#3498db',
                        backgroundColor: 'rgba(52, 152, 219, 0.1)',
                        fill: true,
                        tension: 0.3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 15 } },
                    title: { display: false }
                },
                scales: {
                    y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    // Graphique Tests (Doughnut)
    if (document.getElementById('testsChart') && totalTests > 0) {
        new Chart(document.getElementById('testsChart'), {
            type: 'doughnut',
            data: {
                labels: [
                    formatLabelWithPct('Passés', data.tests.passed, totalTests),
                    formatLabelWithPct('Échoués', data.tests.failed, totalTests),
                    formatLabelWithPct('Erreurs', data.tests.errors, totalTests),
                    formatLabelWithPct('Ignorés', data.tests.skipped, totalTests)
                ],
                datasets: [{
                    data: [data.tests.passed, data.tests.failed, data.tests.errors, data.tests.skipped],
                    backgroundColor: ['#27ae60', '#e74c3c', '#c0392b', '#f39c12'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 10, font: { size: 11 } } },
                    centerText: { display: true, text: data.tests.successRate + '%', subtext: 'succès', color: '#27ae60' }
                },
                cutout: '60%'
            }
        });
    }

    // Graphique Fixtures (Doughnut)
    const totalFixtures = data.fixtures.truePositives + data.fixtures.trueNegatives +
                          data.fixtures.falseNegatives + data.fixtures.falsePositives;
    if (document.getElementById('fixturesChart') && totalFixtures > 0) {
        new Chart(document.getElementById('fixturesChart'), {
            type: 'doughnut',
            data: {
                labels: [
                    formatLabelWithPct('True +', data.fixtures.truePositives, totalFixtures),
                    formatLabelWithPct('True -', data.fixtures.trueNegatives, totalFixtures),
                    formatLabelWithPct('False -', data.fixtures.falseNegatives, totalFixtures),
                    formatLabelWithPct('False +', data.fixtures.falsePositives, totalFixtures)
                ],
                datasets: [{
                    data: [data.fixtures.truePositives, data.fixtures.trueNegatives,
                           data.fixtures.falseNegatives, data.fixtures.falsePositives],
                    backgroundColor: ['#27ae60', '#3498db', '#e74c3c', '#f39c12'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 10, font: { size: 11 } } },
                    centerText: { display: true, text: data.fixtures.successRate + '%', subtext: 'validées', color: '#27ae60' }
                },
                cutout: '60%'
            }
        });
    }

    // Graphique Évolution Tests (Line avec 2 axes)
    if (document.getElementById('testsHistoryChart') && data.history.labels.length > 1) {
        new Chart(document.getElementById('testsHistoryChart'), {
            type: 'line',
            data: {
                labels: data.history.labels,
                datasets: [
                    {
                        label: 'Taux succès (%)',
                        data: data.history.testsRate,
                        borderColor: '#27ae60',
                        backgroundColor: 'rgba(39, 174, 96, 0.1)',
                        fill: true,
                        tension: 0.3,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Tests passés',
                        data: data.history.testsPassed,
                        borderColor: '#3498db',
                        backgroundColor: 'transparent',
                        borderDash: [5, 5],
                        tension: 0.3,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 12, padding: 15 } }
                },
                scales: {
                    y: {
                        type: 'linear',
                        position: 'left',
                        min: 0,
                        max: 100,
                        title: { display: true, text: 'Taux (%)' },
                        grid: { color: 'rgba(0,0,0,0.05)' }
                    },
                    y1: {
                        type: 'linear',
                        position: 'right',
                        min: 0,
                        title: { display: true, text: 'Nombre' },
                        grid: { display: false }
                    },
                    x: { grid: { display: false } }
                }
            }
        });
    }
}
