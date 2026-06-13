import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useAuth } from '../AuthContext';
import ChallengeOverview from '../components/challenge/ChallengeOverview';
import TaskSidebar from '../components/challenge/TaskSidebar';
import TaskDetail from '../components/challenge/TaskDetail';
import NotebookSubmit from '../components/challenge/NotebookSubmit';

export default function Home() {
  const { challengeId } = useParams();
  const { token } = useAuth();
  const { 
    selectedChallenge, 
    setSelectedChallengeById, 
    selectedTask, 
    setSelectedTask 
  } = useApp();

  useEffect(() => {
    if (challengeId) {
      setSelectedChallengeById(parseInt(challengeId));
    }
  }, [challengeId, setSelectedChallengeById]);

  // Set default selected task if none is selected and tasks are available
  useEffect(() => {
    if (selectedChallenge?.tasks?.length > 0 && !selectedTask) {
      setSelectedTask(selectedChallenge.tasks[0]);
    }
  }, [selectedChallenge, selectedTask, setSelectedTask]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }} className="animate-fadein">
      {selectedChallenge ? (
        <>
          <ChallengeOverview challenge={selectedChallenge} />
          
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr',
            gap: 24,
          }} className="lg:grid-cols-[300px_1fr] items-start">
            
            {/* Sidebar with tasks */}
            <div>
              <TaskSidebar 
                tasks={selectedChallenge.tasks} 
                selectedTask={selectedTask} 
                onSelect={setSelectedTask} 
              />
            </div>

            {/* Task Detail and Notebook submission */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              {selectedTask ? (
                <>
                  <TaskDetail task={selectedTask} token={token} />
                  <NotebookSubmit task={selectedTask} challenge={selectedChallenge} />
                </>
              ) : (
                <div className="surface empty-state" style={{ minHeight: 200 }}>
                  <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
                    <path strokeLinecap="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                  <p>No task selected. Select a task from the sidebar to view details and submit.</p>
                </div>
              )}
            </div>

          </div>
        </>
      ) : (
        <div className="surface empty-state" style={{ minHeight: 300 }}>
          <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
            <path strokeLinecap="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <p>No competition selected or active. Please contact a jury or administrator.</p>
        </div>
      )}
    </div>
  );
}
