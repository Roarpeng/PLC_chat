Imports System
Imports System.Windows.Forms
Imports Basic_Project_Generator.Interfaces
Imports Basic_Project_Generator.UserInterfaces

Friend Module Program
    ''' <summary>
    ''' The main entry point for the application.
    ''' </summary>
    <STAThread>
    Public Sub Main()
        Try
            Call Application.EnableVisualStyles()
            Application.SetCompatibleTextRenderingDefault(False)

            If Not IsOpennessInstalled() Then
                Throw New Exception($"TIA Portal Openness {ApiResolver.Version} is not installed.")
            End If
            AddHandler AppDomain.CurrentDomain.AssemblyResolve, AddressOf AssemblyResolver

            Call Application.Run(New BasicProjectGenerator())
        Catch ex As Exception
            MessageBox.Show($"{ex.Message}{Environment.NewLine}{Environment.NewLine}Details:{Environment.NewLine}{ex}", "Basic Project Generator", MessageBoxButtons.OK, MessageBoxIcon.Error)
        End Try
    End Sub
End Module
