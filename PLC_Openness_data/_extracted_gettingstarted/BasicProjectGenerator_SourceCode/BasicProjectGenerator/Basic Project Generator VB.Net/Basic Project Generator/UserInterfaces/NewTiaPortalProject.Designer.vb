Namespace UserInterfaces
    Partial Class NewTiaPortalProject
        Inherits System.Windows.Forms.Form
        ''' <summary>
        ''' Required designer variable.
        ''' </summary>
        Private components As System.ComponentModel.IContainer = Nothing

        ''' <summary>
        ''' Clean up any resources being used.
        ''' </summary>
        ''' <paramname="disposing">true if managed resources should be disposed; otherwise, false.</param>
        Protected Overrides Sub Dispose(ByVal disposing As Boolean)
            If disposing AndAlso components IsNot Nothing Then
                components.Dispose()
            End If

            MyBase.Dispose(disposing)
        End Sub

#Region "Windows Form Designer generated code"

        ''' <summary>
        ''' Required method for Designer support - do not modify
        ''' the contents of this method with the code editor.
        ''' </summary>
        Private Sub InitializeComponent()
        Me.lab_ProjectName = New System.Windows.Forms.Label()
        Me.txb_ProjectName = New System.Windows.Forms.TextBox()
        Me.lab_Path = New System.Windows.Forms.Label()
        Me.txb_Path = New System.Windows.Forms.TextBox()
        Me.btn_Create = New System.Windows.Forms.Button()
        Me.btn_Cancel = New System.Windows.Forms.Button()
        Me.btn_Path = New System.Windows.Forms.Button()
        Me.SuspendLayout
        '
        'lab_ProjectName
        '
        Me.lab_ProjectName.Location = New System.Drawing.Point(12, 19)
        Me.lab_ProjectName.Name = "lab_ProjectName"
        Me.lab_ProjectName.Size = New System.Drawing.Size(81, 20)
        Me.lab_ProjectName.TabIndex = 0
        Me.lab_ProjectName.Text = "Project name"
        '
        'txb_ProjectName
        '
        Me.txb_ProjectName.Location = New System.Drawing.Point(99, 19)
        Me.txb_ProjectName.Name = "txb_ProjectName"
        Me.txb_ProjectName.Size = New System.Drawing.Size(254, 20)
        Me.txb_ProjectName.TabIndex = 1
        '
        'lab_Path
        '
        Me.lab_Path.Location = New System.Drawing.Point(12, 45)
        Me.lab_Path.Name = "lab_Path"
        Me.lab_Path.Size = New System.Drawing.Size(81, 20)
        Me.lab_Path.TabIndex = 2
        Me.lab_Path.Text = "Directory path"
        '
        'txb_Path
        '
        Me.txb_Path.Location = New System.Drawing.Point(99, 45)
        Me.txb_Path.Name = "txb_Path"
        Me.txb_Path.Size = New System.Drawing.Size(254, 20)
        Me.txb_Path.TabIndex = 3
        '
        'btn_Create
        '
        Me.btn_Create.Location = New System.Drawing.Point(149, 71)
        Me.btn_Create.Name = "btn_Create"
        Me.btn_Create.Size = New System.Drawing.Size(99, 23)
        Me.btn_Create.TabIndex = 5
        Me.btn_Create.Text = "Create"
        Me.btn_Create.UseVisualStyleBackColor = true
        '
        'btn_Cancel
        '
        Me.btn_Cancel.Location = New System.Drawing.Point(254, 71)
        Me.btn_Cancel.Name = "btn_Cancel"
        Me.btn_Cancel.Size = New System.Drawing.Size(99, 23)
        Me.btn_Cancel.TabIndex = 6
        Me.btn_Cancel.Text = "Cancel"
        Me.btn_Cancel.UseVisualStyleBackColor = true
        '
        'btn_Path
        '
        Me.btn_Path.Location = New System.Drawing.Point(359, 45)
        Me.btn_Path.Name = "btn_Path"
        Me.btn_Path.Size = New System.Drawing.Size(29, 20)
        Me.btn_Path.TabIndex = 4
        Me.btn_Path.Text = "..."
        Me.btn_Path.UseVisualStyleBackColor = true
        '
        'NewTiaPortalProject
        '
        Me.AutoScaleDimensions = New System.Drawing.SizeF(6!, 13!)
        Me.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font
        Me.ClientSize = New System.Drawing.Size(414, 116)
        Me.ControlBox = false
        Me.Controls.Add(Me.btn_Path)
        Me.Controls.Add(Me.btn_Cancel)
        Me.Controls.Add(Me.btn_Create)
        Me.Controls.Add(Me.txb_Path)
        Me.Controls.Add(Me.lab_Path)
        Me.Controls.Add(Me.txb_ProjectName)
        Me.Controls.Add(Me.lab_ProjectName)
        Me.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog
        Me.MaximizeBox = false
        Me.MinimizeBox = false
        Me.Name = "NewTiaPortalProject"
        Me.ShowInTaskbar = false
        Me.StartPosition = System.Windows.Forms.FormStartPosition.CenterParent
        Me.Text = "Create a new TIA Portal project"
        Me.ResumeLayout(false)
        Me.PerformLayout

End Sub

#End Region

        Private WithEvents lab_ProjectName As System.Windows.Forms.Label
        Private WithEvents txb_ProjectName As System.Windows.Forms.TextBox
        Private WithEvents lab_Path As System.Windows.Forms.Label
        Private WithEvents txb_Path As System.Windows.Forms.TextBox
        Private WithEvents btn_Create As System.Windows.Forms.Button
        Private WithEvents btn_Cancel As System.Windows.Forms.Button
        Private WithEvents btn_Path As System.Windows.Forms.Button
    End Class
End Namespace
