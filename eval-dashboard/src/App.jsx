import React, { useState, useMemo } from 'react';
import ExperimentDashboard from './ExperimentDashboard';

// 1. Vite magic: Read all JSON files in the data directory
const dataFiles = import.meta.glob('./data/*.json', { eager: true });

function App() {
  const latestData = useMemo(() => {
    // Convert the Vite object into an array of JSON data
    const allRuns = Object.values(dataFiles).map(file => file.default || file);

    if (allRuns.length === 0) return null;

    // Sort them by timestamp (newest first)
    allRuns.sort((a, b) => {
      const timeA = new Date(a.experiment.timestamp).getTime();
      const timeB = new Date(b.experiment.timestamp).getTime();
      return timeB - timeA; 
    });

    // Return the newest one
    return allRuns[0];
  }, []);

  if (!latestData) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6 text-slate-500">
        <div className="text-center">
          <h2 className="text-xl font-bold mb-2">No Data Found</h2>
          <p>Please add your JSON files to the <code>src/data</code> directory.</p>
        </div>
      </div>
    );
  }

  return <ExperimentDashboard data={latestData} />;
}

export default App;