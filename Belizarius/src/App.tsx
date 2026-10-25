
import { useEffect, useState } from 'react'
import belizariusImage from './assets/belizarius.jpg'
import './App.css'

type Mood = 'IDLE' | 'LISTENING' | 'THINKING'

function App() {
  const [mood, setMood] = useState<Mood>('IDLE')
  const [wakePhrase, setWakePhrase] = useState('')

  useEffect(() => {
    const unsubscribe = window.electronAPI.onWakeWord((phrase) => {
      console.log('Belizarius activated:', phrase)
      setWakePhrase(phrase)
      setMood('LISTENING')
    })

    return unsubscribe
  }, [])

  return (
    <main className="companion">
      <div className={`aura aura-${mood.toLowerCase()}`} />

      <img
        className="character"
        src={belizariusImage}
        alt="Belizarius"
        draggable={false}
      />

      <section className="companion-ui">
        <div className="name">BELIZARIUS</div>
        <div className="status">{mood}</div>

        {wakePhrase && (
          <div className="wake-phrase">
            Activated: {wakePhrase}
          </div>
        )}

        <div className="controls">
          <button onClick={() => setMood('LISTENING')}>
            Listen
          </button>
          <button onClick={() => setMood('THINKING')}>
            Think
          </button>
          <button onClick={() => setMood('IDLE')}>
            Idle
          </button>
        </div>
      </section>
    </main>
  )
}

export default App
