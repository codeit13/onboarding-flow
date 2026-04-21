// Utility functions for handling beep sounds and tab visibility detection
// Enhanced version with better browser compatibility and error handling

// Audio context management
let audioContext: AudioContext | null = null
let currentOscillator: OscillatorNode | null = null

/**
 * Initialize audio context with user interaction support
 * Required by modern browsers for audio playback
 */
const initAudioContext = async (): Promise<AudioContext | null> => {
  try {
    if (!audioContext || audioContext.state === 'closed') {
      // Support for different browser implementations
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
      if (!AudioContextClass) {
        console.warn('AudioContext not supported in this browser')
        return null
      }
      audioContext = new AudioContextClass()
    }
    
    // Resume audio context if suspended (required by some browsers)
    if (audioContext.state === 'suspended') {
      await audioContext.resume()
      console.log('Audio context resumed successfully')
    }
    
    return audioContext
  } catch (error) {
    console.error('Error initializing audio context:', error)
    return null
  }
}

/**
 * Start playing a beep sound at specified frequency
 * @param frequency - Frequency of the beep in Hz (default: 800)
 */
export const startBeep = async (frequency: number = 800): Promise<void> => {
  try {
    const context = await initAudioContext()
    if (!context) {
      console.error('Audio context not available - cannot start beep')
      return
    }

    // Stop any existing beep first to prevent overlap
    if (currentOscillator) {
      try {
        currentOscillator.stop()
        currentOscillator.disconnect()
      } catch (e) {
        console.log('Previous oscillator already stopped')
      }
    }

    // Create oscillator and gain node for volume control
    currentOscillator = context.createOscillator()
    const gainNode = context.createGain()
    
    // Configure oscillator
    currentOscillator.type = 'sine'
    currentOscillator.frequency.setValueAtTime(frequency, context.currentTime)
    
    // Set volume (0.3 = 30% volume to avoid being too loud)
    gainNode.gain.setValueAtTime(0.3, context.currentTime)
    
    // Connect audio nodes: oscillator -> gain -> speakers
    currentOscillator.connect(gainNode)
    gainNode.connect(context.destination)
    
    // Start the beep
    currentOscillator.start()
    console.log(`Beep started at frequency: ${frequency}Hz`)
  } catch (error) {
    console.error('Error starting beep:', error)
  }
}

/**
 * Stop the currently playing beep sound
 */
export const stopBeep = (): void => {
  try {
    if (currentOscillator) {
      currentOscillator.stop()
      currentOscillator.disconnect()
      currentOscillator = null
      console.log('Beep stopped successfully')
    }
  } catch (error) {
    console.error('Error stopping beep:', error)
  }
}

/**
 * Play a beep sound for a specific duration
 * @param duration - Duration in milliseconds (default: 2000ms)
 * @param frequency - Frequency in Hz (default: 800Hz)
 */
export const playBeep = async (duration: number = 2000, frequency: number = 800): Promise<void> => {
  try {
    console.log(`Playing beep for ${duration}ms at ${frequency}Hz`)
    
    // Initialize audio context first
    const context = await initAudioContext()
    if (!context) {
      console.error('Cannot play beep - audio context not available')
      await playBeepFallback(duration)
      return
    }
    
    // Start the beep
    await startBeep(frequency)
    
    // Stop after specified duration
    setTimeout(() => {
      stopBeep()
      console.log('Beep finished')
    }, duration)
  } catch (error) {
    console.error('Error playing beep:', error)
    // Try fallback method
    await playBeepFallback(duration)
  }
}

/**
 * Fallback beep method using HTML5 Audio
 * Used when AudioContext is not available
 * @param duration - Duration in milliseconds
 */
const playBeepFallback = async (duration: number = 2000): Promise<void> => {
  try {
    console.log('Using fallback audio beep method')
    
    // Create a temporary audio context for fallback
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
    if (!AudioContextClass) {
      console.warn('No audio support available')
      return
    }
    
    const tempContext = new AudioContextClass()
    const oscillator = tempContext.createOscillator()
    const gainNode = tempContext.createGain()
    
    oscillator.connect(gainNode)
    gainNode.connect(tempContext.destination)
    
    oscillator.frequency.value = 800
    oscillator.type = 'sine'
    gainNode.gain.value = 0.3
    
    oscillator.start()
    
    setTimeout(() => {
      oscillator.stop()
      tempContext.close()
    }, duration)
  } catch (error) {
    console.error('Fallback beep also failed:', error)
  }
}

/**
 * Enhanced playBeep with automatic fallback
 * @param duration - Duration in milliseconds (default: 2000ms)
 * @param frequency - Frequency in Hz (default: 800Hz)
 */
export const playBeepWithFallback = async (duration: number = 2000, frequency: number = 800): Promise<void> => {
  try {
    console.log('Attempting to play beep with fallback support...')
    await playBeep(duration, frequency)
  } catch (error) {
    console.log('Primary beep failed, trying fallback...')
    await playBeepFallback(duration)
  }
}

/**
 * Set up tab visibility detection to trigger alerts when user switches tabs
 * This is important for interview integrity monitoring
 * @param onTabSwitch - Callback function to execute when tab is switched
 * @returns Cleanup function to remove event listeners
 */
export const setupTabVisibilityDetection = (onTabSwitch: () => void): (() => void) => {
  // Handle visibility change (primary method)
  const handleVisibilityChange = () => {
    if (document.hidden) {
      console.log('Tab visibility lost - triggering alert')
      onTabSwitch()
    }
  }

  // Handle window focus/blur as backup method
  const handleWindowBlur = () => {
    console.log('Window lost focus - triggering alert')
    onTabSwitch()
  }

  // Handle page visibility change (alternative API)
  const handlePageHide = () => {
    console.log('Page hidden - triggering alert')
    onTabSwitch()
  }

  // Add multiple event listeners for better coverage
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('blur', handleWindowBlur)
  window.addEventListener('pagehide', handlePageHide)

  // Return cleanup function to remove all listeners
  return () => {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    window.removeEventListener('blur', handleWindowBlur)
    window.removeEventListener('pagehide', handlePageHide)
    console.log('Tab visibility detection cleaned up')
  }
}

/**
 * Test function to verify beep functionality
 * Useful for debugging audio issues
 */
export const testBeep = async (): Promise<void> => {
  console.log('Testing beep functionality...')
  try {
    await playBeepWithFallback(1000, 800)
    console.log('Beep test completed successfully')
  } catch (error) {
    console.error('Beep test failed:', error)
  }
}

/**
 * Initialize audio context on user interaction
 * Call this on first user click/tap to enable audio
 */
export const initializeAudioOnUserInteraction = async (): Promise<boolean> => {
  try {
    const context = await initAudioContext()
    return context !== null
  } catch (error) {
    console.error('Failed to initialize audio on user interaction:', error)
    return false
  }
}

/**
 * Check if audio is supported in the current browser
 * @returns boolean indicating audio support
 */
export const isAudioSupported = (): boolean => {
  try {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
    return !!AudioContextClass
  } catch (error) {
    return false
  }
}

/**
 * Get current audio context state
 * Useful for debugging audio issues
 */
export const getAudioContextState = (): string => {
  if (!audioContext) return 'not-initialized'
  return audioContext.state
}

// Export type definitions for TypeScript
export interface AudioConfig {
  frequency?: number
  duration?: number
  volume?: number
}

export interface TabVisibilityConfig {
  enableVisibilityChange?: boolean
  enableWindowBlur?: boolean
  enablePageHide?: boolean
}