import React, { useEffect } from 'react';
import { useParams } from 'react-router';
import { useApp } from '../context/AppContext';
import ChallengeOverview from '../components/challenge/ChallengeOverview';
import TaskSidebar from '../components/challenge/TaskSidebar';
import TaskDetail from '../components/challenge/TaskDetail';
import NotebookSubmit from '../components/challenge/NotebookSubmit';
import EmptyState from '../components/ui/EmptyState';
import ChallengeNotFound from '../components/challenge/ChallengeNotFound';
import useChallengeNotFound from '../hooks/useChallengeNotFound';
import { useTranslation } from 'react-i18next';
import { FileText, AlertTriangle } from 'lucide-react';

export default function Home() {
  const { challengeId } = useParams();
  const { selectedChallenge, setSelectedChallengeById, selectedTask, setSelectedTask } = useApp();
  const { t } = useTranslation();
  const notFound = useChallengeNotFound(challengeId);

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

  if (notFound) return <ChallengeNotFound />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }} className="animate-fadein">
      {selectedChallenge ? (
        <>
          <ChallengeOverview challenge={selectedChallenge} />

          {/* minmax(0, 1fr) lets wide task content (tables, code) scroll instead of
              stretching the page; an inline gridTemplateColumns would override lg: */}
          <div className="grid grid-cols-1 gap-6 items-start lg:grid-cols-[300px_minmax(0,1fr)]">
            {/* Sidebar with tasks */}
            <div className="min-w-0">
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
              className="animate-fadein min-w-0"
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
