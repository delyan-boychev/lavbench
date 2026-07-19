import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import ChallengeOverview from '../components/challenge/ChallengeOverview';
import TaskSidebar from '../components/challenge/TaskSidebar';
import TaskDetail from '../components/challenge/TaskDetail';
import NotebookSubmit from '../components/challenge/NotebookSubmit';
import EmptyState from '../components/ui/EmptyState';
import { useTranslation } from 'react-i18next';
import { FileText, AlertTriangle } from 'lucide-react';

export default function Home() {
  const { challengeId } = useParams();
  const { selectedChallenge, setSelectedChallengeById, selectedTask, setSelectedTask } = useApp();
  const { t } = useTranslation();

  useEffect(() => {
    if (challengeId) {
      setSelectedChallengeById(challengeId);
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

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr',
              gap: 24,
            }}
            className="lg:grid-cols-[300px_1fr] items-start"
          >
            {/* Sidebar with tasks */}
            <div>
              <TaskSidebar
                tasks={selectedChallenge.tasks}
                selectedTask={selectedTask}
                onSelect={setSelectedTask}
              />
            </div>

            {/* Task Detail and Notebook submission */}
            <div
              key={selectedTask?.id || 'no-task'}
              style={{ display: 'flex', flexDirection: 'column', gap: 24 }}
              className="animate-fadein"
            >
              {selectedTask ? (
                <>
                  <TaskDetail task={selectedTask} />
                  <NotebookSubmit task={selectedTask} challenge={selectedChallenge} />
                </>
              ) : (
                <EmptyState
                  minHeight={200}
                  message={t('challenge.no_task_selected')}
                  icon={<FileText size={32} />}
                />
              )}
            </div>
          </div>
        </>
      ) : (
        <EmptyState
          minHeight={300}
          message={t('challenge.no_competition_selected')}
          icon={<AlertTriangle size={32} />}
        />
      )}
    </div>
  );
}
