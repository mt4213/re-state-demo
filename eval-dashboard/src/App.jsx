import React, { useState, useMemo } from 'react';
import ExperimentDashboard from './ExperimentDashboard';

// 1. Vite magic: Read all JSON files in data directory
const dataFiles = import.meta.glob('./data/*.json', { eager: true });

function App() {
  const aggregatedData = useMemo(() => {
    // Convert Vite object into an array of JSON data
    const allFiles = Object.values(dataFiles).map(file => file.default || file);

    if (allFiles.length === 0) return null;

    // Sort files by timestamp (newest first) for experiment metadata
    allFiles.sort((a, b) => {
      const timeA = new Date(a.experiment.timestamp).getTime();
      const timeB = new Date(b.experiment.timestamp).getTime();
      return timeB - timeA;
    });

    // Use newest file for experiment metadata
    const latestFile = allFiles[0];

    // Collect ALL runs from ALL files
    const allRuns = allFiles.flatMap(file => {
      const runs = file.runs || [];
      // Tag runs with their source file timestamp for traceability
      return runs.map(run => ({
        ...run,
        source_file_timestamp: file.experiment.timestamp,
        source_file_condition: file.experiment.condition,
      }));
    });

    // Create aggregated result combining all data
    return {
      experiment: {
        ...latestFile.experiment,
        num_runs: allRuns.length,
        aggregated_files_count: allFiles.length,
        source_files: allFiles.map(f => ({
          timestamp: f.experiment.timestamp,
          condition: f.experiment.condition,
          runs_in_file: f.runs?.length || 0,
        })),
      },
      runs: allRuns,
    };
  }, []);

  if (!aggregatedData) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6 text-slate-500">
        <div className="text-center">
          <h2 className="text-xl font-bold mb-2">No Data Found</h2>
          <p>Please add your JSON files to <code>src/data</code> directory.</p>
        </div>
      </div>
    );
  }

  return <ExperimentDashboard data={aggregatedData} />;
}

export default App;
